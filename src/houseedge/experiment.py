from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

from houseedge.config import load_yaml, PoolSpec, canonical_hash
from houseedge.data.reference import normalize_reference
from houseedge.data.storage import read_frame, write_frame
from houseedge.research.alignment import align_reference, alignment_sensitivity
from houseedge.research.markouts import compute_markouts, shuffled_direction_null
from houseedge.research.replay import replay_discrete_hedged_lp
from houseedge.research.bootstrap import stationary_bootstrap_sums, ci
from houseedge.research.capacity import capacity_sweep


def run_experiment(swaps: pd.DataFrame, reference: pd.DataFrame, cfg: dict, output_dir: str | Path) -> dict:
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    spec=PoolSpec.from_config(cfg)
    swaps=swaps[swaps.get("event",pd.Series("Swap",index=swaps.index)).eq("Swap")].copy()
    swaps["timestamp"]=pd.to_datetime(swaps["timestamp"],utc=True)
    reference=normalize_reference(reference)

    sample=cfg["sample"]
    aligned=align_reference(swaps,reference,float(sample["primary_alignment_tolerance_seconds"]),0)
    match_rate=float(aligned["ref_mid"].notna().mean())
    if match_rate < 0.80:
        raise RuntimeError(f"Only {match_rate:.1%} of swaps aligned to reference data. Fix coverage/alignment before interpreting results.")

    shifts=alignment_sensitivity(swaps,reference,list(sample["alignment_shift_diagnostics_seconds"]),float(sample["primary_alignment_tolerance_seconds"]))
    markouts=compute_markouts(aligned,reference,list(sample["markout_horizons_seconds"]),float(sample["primary_alignment_tolerance_seconds"]))
    nulls=shuffled_direction_null(markouts,list(sample["markout_horizons_seconds"]),reps=1000)

    p=cfg["position"]; h=cfg["hedge"]
    replay_kwargs=dict(
        lower_multiplier=float(p["lower_multiplier"]), upper_multiplier=float(p["upper_multiplier"]),
        swap_fee_rate=float(spec.fee_tier_pips)/1_000_000.0,
        lp_fee_fraction=float(spec.lp_share_of_swap_fee), delta_band_usd=float(h["delta_band_usd"]),
        hedge_taker_cost_bps=float(h["taker_cost_bps"]), annualized_funding_rate=float(h["annualized_funding_rate"]),
        fixed_operating_cost_usd=float(h["fixed_operating_cost_usd"]), boundary_cross_fee_policy=str(p["boundary_cross_fee_policy"]),
        token0_decimals=spec.token0_decimals, token1_decimals=spec.token1_decimals,
    )
    path,summary=replay_discrete_hedged_lp(aligned,capital_usd=float(p["initial_capital_usd"]),**replay_kwargs)

    inf=cfg["inference"]
    boot_sums=stationary_bootstrap_sums(path["net_pnl_inc_usd"].to_numpy(),int(inf["stationary_bootstrap_reps"]),float(inf["stationary_bootstrap_mean_block_swaps"]))
    boot_returns=boot_sums/summary.initial_capital_usd
    annual_factor=365.0/summary.duration_days
    boot_ann=np.where(boot_returns>-1,(1+boot_returns)**annual_factor-1,-1.0)
    lo,hi=ci(boot_ann,float(inf["confidence_level"]))
    research_go=bool(lo>0)
    production_hurdle=bool(summary.annualized_net_hedged_return>=float(inf["production_hurdle_annualized_net_return"]) and np.isfinite(summary.hedged_sharpe) and summary.hedged_sharpe>=float(inf["production_hurdle_hedged_sharpe"]))

    capacity=capacity_sweep(aligned,[float(x) for x in cfg["capacity"]["capital_usd"]],replay_kwargs)

    write_frame(aligned,out/"aligned_swaps.parquet")
    write_frame(markouts,out/"markouts.parquet")
    write_frame(shifts,out/"alignment_sensitivity.csv")
    write_frame(nulls,out/"markout_nulls.csv")
    write_frame(path,out/"hedged_replay.parquet")
    write_frame(capacity,out/"capacity.csv")
    write_frame(pd.DataFrame({"annualized_return":boot_ann}),out/"bootstrap.parquet")

    result={
        "experiment_id":cfg["experiment_id"],"spec_sha256":canonical_hash(cfg),"reference_match_rate":match_rate,
        "primary":summary.as_dict(),"bootstrap":{"confidence_level":float(inf["confidence_level"]),"annualized_return_lower":lo,"annualized_return_upper":hi},
        "research_go":research_go,"production_hurdle_met_in_sample":production_hurdle,
        "decision":"GO_TO_PHASE_2" if research_go else "KILL_OR_REDESIGN",
        "warnings":[
            "Markouts are flow-quality diagnostics, not LVR or hedged P&L.",
            "Capacity is a passive counterfactual; large hypothetical positions may alter routing/execution.",
            "Confirm the actual v3 protocol-fee configuration for this pool before a real GO decision.",
            "A production hurdle met in this one sample is not production approval."
        ]
    }
    (out/"summary.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
    return result
