from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

from houseedge.config import PoolSpec, canonical_hash
from houseedge.data.reference import normalize_reference
from houseedge.data.storage import write_frame
from houseedge.research.alignment import align_reference, alignment_sensitivity
from houseedge.research.markouts import compute_markouts, shuffled_direction_null
from houseedge.research.replay import replay_discrete_hedged_lp
from houseedge.research.bootstrap import stationary_bootstrap_sums, ci
from houseedge.research.capacity import capacity_sweep
from houseedge.research.benchmark import time_weighted_apy_return
from houseedge.research.validation import evaluate_void_criteria, ValidityResult


def _funding_gap_hours(funding: pd.DataFrame | None, start: pd.Timestamp, end: pd.Timestamp, expected_interval_hours: float | None) -> float:
    if funding is None or funding.empty:
        return float("inf")
    if expected_interval_hours is None:
        return 0.0
    t=pd.to_datetime(funding["timestamp"],utc=True).sort_values()
    points=pd.Series([start,*t[(t>=start)&(t<=end)].tolist(),end]).sort_values().reset_index(drop=True)
    gaps=points.diff().dt.total_seconds().dropna()/3600.0
    return max(0.0,float(gaps.max())-float(expected_interval_hours)) if len(gaps) else 0.0


def _sample_bounds(cfg: dict) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    sample=cfg.get("sample",{})
    if not sample.get("start") or not sample.get("end"):
        return None,None
    start=pd.Timestamp(sample["start"]); end=pd.Timestamp(sample["end"])
    if start.tzinfo is None: start=start.tz_localize("UTC")
    if end.tzinfo is None: end=end.tz_localize("UTC")
    return start,end


def preflight_primary_inputs(
    swaps: pd.DataFrame,
    reference: pd.DataFrame,
    funding_events: pd.DataFrame,
    cfg: dict,
    *,
    replay_state_valid: bool,
    micro_live_fee_error_bps_nav: float | None,
) -> ValidityResult:
    """Outcome-blind input validity check. Does not compute LP P&L."""
    start,end=_sample_bounds(cfg)
    x=swaps.copy(); x["timestamp"]=pd.to_datetime(x["timestamp"],utc=True)
    if start is not None:
        x=x[(x["timestamp"]>=start)&(x["timestamp"]<=end)]
    x=x[x.get("event",pd.Series("Swap",index=x.index)).eq("Swap")].copy()
    ref=normalize_reference(reference)
    tolerance=float(cfg["sample"].get("primary_alignment",{}).get("max_age_seconds",3.0))
    aligned=align_reference(x,ref,tolerance,0)
    missing=1.0-float(aligned["ref_mid"].notna().mean()) if len(aligned) else 1.0
    f=funding_events.copy(); f["timestamp"]=pd.to_datetime(f["timestamp"],utc=True)
    if start is None and len(aligned): start=pd.Timestamp(aligned["timestamp"].min())
    if end is None and len(aligned): end=pd.Timestamp(aligned["timestamp"].max())
    h=cfg["hedge"]
    funding_gap=_funding_gap_hours(f,start,end,float(h["expected_funding_interval_hours"])) if start is not None and end is not None else float("inf")
    protocol_complete=("lp_fee_fraction" in aligned and aligned["lp_fee_fraction"].notna().all() and "fee_protocol_packed" in aligned)
    vcfg=cfg.get("validity",{})
    return evaluate_void_criteria(
        missing_reference_fraction=missing,max_missing_reference_fraction=float(vcfg.get("max_missing_reference_fraction",0.005)),
        funding_gap_hours=funding_gap,max_funding_gap_hours=float(vcfg.get("max_unresolved_funding_gap_hours",0.0)),
        protocol_fee_history_complete=protocol_complete,replay_state_valid=replay_state_valid,
        micro_live_fee_error_bps_nav=micro_live_fee_error_bps_nav,
        max_micro_live_fee_error_bps_nav=float(vcfg.get("micro_live",{}).get("max_fee_reconciliation_error_bps_nav",1.0)),
    )


def run_experiment(
    swaps: pd.DataFrame,
    reference: pd.DataFrame,
    cfg: dict,
    output_dir: str | Path,
    *,
    funding_events: pd.DataFrame | None,
    benchmark_rates: pd.DataFrame | None,
    outcome_look_number: int,
    replay_state_valid: bool = False,
    micro_live_fee_error_bps_nav: float | None = None,
    synthetic: bool = False,
) -> dict:
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    spec=PoolSpec.from_config(cfg)
    swaps=swaps[swaps.get("event",pd.Series("Swap",index=swaps.index)).eq("Swap")].copy()
    swaps["timestamp"]=pd.to_datetime(swaps["timestamp"],utc=True)
    sample_start,sample_end=_sample_bounds(cfg)
    if not synthetic and sample_start is not None:
        swaps=swaps[(swaps["timestamp"]>=sample_start)&(swaps["timestamp"]<=sample_end)].copy()
    reference=normalize_reference(reference)

    sample=cfg["sample"]
    align_cfg=sample.get("primary_alignment",{})
    tolerance=float(align_cfg.get("max_age_seconds",3.0))
    aligned=align_reference(swaps,reference,tolerance,0)
    match_rate=float(aligned["ref_mid"].notna().mean())
    missing_fraction=1.0-match_rate

    shifts=alignment_sensitivity(swaps,reference,list(sample["alignment_shift_diagnostics_seconds"]),tolerance)
    markouts=compute_markouts(aligned,reference,list(sample["markout_horizons_seconds"]),tolerance)
    nulls=shuffled_direction_null(markouts,list(sample["markout_horizons_seconds"]),reps=1000)

    p=cfg["position"]; h=cfg["hedge"]
    replay_kwargs=dict(
        lower_multiplier=float(p["lower_multiplier"]), upper_multiplier=float(p["upper_multiplier"]),
        swap_fee_rate=float(spec.fee_tier_pips)/1_000_000.0,
        lp_fee_fraction=float(getattr(spec,"lp_share_of_swap_fee",1.0)),
        delta_band_fraction_nav=float(h["trigger_residual_delta_fraction_lp_nav"]),
        hedge_to_zero=str(h.get("rebalance_target","zero")).lower()=="zero",
        hedge_taker_cost_bps=float(h["taker_cost_bps"]),
        funding_events=funding_events,
        annualized_funding_rate=0.0 if synthetic else None,
        fixed_operating_cost_usd=0.0,
        charge_initial_and_final_hedge_costs=bool(h.get("charge_initial_and_final_hedge_costs",True)),
        boundary_cross_fee_policy=str(p["boundary_cross_fee_policy"]),
        token0_decimals=spec.token0_decimals, token1_decimals=spec.token1_decimals,
    )
    path,summary=replay_discrete_hedged_lp(aligned,capital_usd=float(p["initial_capital_usd"]),**replay_kwargs)

    start=pd.Timestamp(path.iloc[0].timestamp); end=pd.Timestamp(path.iloc[-1].timestamp)
    if benchmark_rates is None:
        if not synthetic:
            raise RuntimeError("Real primary replay requires the precommitted on-chain cash benchmark rate series.")
        benchmark_window_return=0.0; benchmark_ann=0.0
    else:
        benchmark_window_return,benchmark_ann=time_weighted_apy_return(benchmark_rates,start,end)

    inf=cfg["inference"]
    boot_sums=stationary_bootstrap_sums(path["net_pnl_inc_usd"].to_numpy(),int(inf["stationary_bootstrap_reps"]),float(inf["stationary_bootstrap_mean_block_swaps"]))
    boot_returns=boot_sums/summary.initial_capital_usd
    annual_factor=365.0/summary.duration_days
    boot_ann=np.where(boot_returns>-1,(1+boot_returns)**annual_factor-1,-1.0)
    boot_excess=boot_ann-benchmark_ann
    lo,hi=ci(boot_excess,float(inf["confidence_level"]))
    point_excess=summary.annualized_net_hedged_return-benchmark_ann
    statistical_go=bool(lo>0)
    economic_hurdle=float(cfg["benchmark"]["annual_excess_return_hurdle"])
    economic_go=bool(point_excess>=economic_hurdle)

    capacity=capacity_sweep(aligned,[float(x) for x in cfg["capacity"]["capital_usd"]],replay_kwargs)
    capacity["annualized_excess_return"]=capacity["annualized_net_return"]-benchmark_ann
    capacity["expected_annual_excess_profit_usd"]=capacity["capital_usd"]*capacity["annualized_excess_return"]
    viable=capacity[capacity["annualized_excess_return"]>=economic_hurdle]
    max_prize=float(viable["expected_annual_excess_profit_usd"].max()) if not viable.empty else float("-inf")
    capacity_go=bool(max_prize>=float(cfg["capacity"]["minimum_expected_annual_excess_profit_usd"]))

    expected_funding_interval=h.get("expected_funding_interval_hours")
    funding_gap=0.0 if synthetic else _funding_gap_hours(funding_events,start,end,None if expected_funding_interval is None else float(expected_funding_interval))
    protocol_complete=synthetic or ("lp_fee_fraction" in aligned and aligned["lp_fee_fraction"].notna().all() and "fee_protocol_packed" in aligned)
    vcfg=cfg.get("validity",{})
    validity=evaluate_void_criteria(
        missing_reference_fraction=missing_fraction,
        max_missing_reference_fraction=float(vcfg.get("max_missing_reference_fraction",0.005)),
        funding_gap_hours=funding_gap,
        max_funding_gap_hours=float(vcfg.get("max_unresolved_funding_gap_hours",0.0)),
        protocol_fee_history_complete=protocol_complete,
        replay_state_valid=True if synthetic else replay_state_valid,
        micro_live_fee_error_bps_nav=micro_live_fee_error_bps_nav,
        max_micro_live_fee_error_bps_nav=float(vcfg.get("micro_live",{}).get("max_fee_reconciliation_error_bps_nav",1.0)),
    )

    if synthetic:
        decision="SYNTHETIC_ONLY"
    elif validity.status=="VOID":
        decision="VOID"
    elif micro_live_fee_error_bps_nav is None:
        decision="PENDING_MICRO_LIVE_RECONCILIATION"
    elif statistical_go and economic_go and capacity_go:
        decision="GO"
    else:
        decision="KILL"

    write_frame(aligned,out/"aligned_swaps.parquet")
    write_frame(markouts,out/"markouts.parquet")
    write_frame(shifts,out/"alignment_sensitivity.csv")
    write_frame(nulls,out/"markout_nulls.csv")
    write_frame(path,out/"hedged_replay.parquet")
    write_frame(capacity,out/"capacity.csv")
    write_frame(pd.DataFrame({"annualized_return":boot_ann,"annualized_excess_return":boot_excess}),out/"bootstrap.parquet")

    result={
        "experiment_id":cfg["experiment_id"],"spec_sha256":canonical_hash(cfg),"outcome_look_number":outcome_look_number,
        "reference_match_rate":match_rate,"validity":validity.as_dict(),
        "primary":summary.as_dict(),
        "benchmark":{"window_return":benchmark_window_return,"annualized_return":benchmark_ann,"name":cfg.get("benchmark",{}).get("name","synthetic_zero")},
        "excess":{"annualized_point_estimate":point_excess,"confidence_level":float(inf["confidence_level"]),"annualized_lower":lo,"annualized_upper":hi},
        "gates":{"statistical":statistical_go,"economic":economic_go,"capacity":capacity_go,"max_expected_annual_excess_profit_usd":max_prize},
        "decision":decision,
        "warnings":[
            "Markouts are flow-quality diagnostics, not LVR or hedged P&L.",
            "Capacity is a passive counterfactual; large hypothetical positions may alter routing/execution.",
            "Range optimization is not permitted to rescue an Experiment 001 KILL.",
            "Every post-unblind rerun is a new EdgeLab look/trial."
        ]
    }
    (out/"summary.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
    return result
