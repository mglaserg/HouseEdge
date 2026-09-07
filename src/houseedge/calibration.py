from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from houseedge.config import canonical_hash, calibration_basis_hash
from houseedge.research.alignment import align_reference
from houseedge.research.benchmark import time_weighted_apy_return
from houseedge.research.gate0 import gate0_from_tape
from houseedge.research.jit import jit_dilution_diagnostic
from houseedge.research.power import prospective_power
from houseedge.research.bootstrap import estimate_mean_block_length
from houseedge.research.regime import check_regime_coverage, daily_realized_variance
from houseedge.data.storage import write_frame


def run_design_calibration(
    *,
    calibration_excess_increments: pd.DataFrame,
    calibration_reference: pd.DataFrame,
    candidate_reference: pd.DataFrame,
    candidate_events: pd.DataFrame,
    benchmark_rates: pd.DataFrame,
    cfg: dict,
    output_dir: str | Path,
) -> dict:
    """Run v0.15 outcome-blind design gates without primary hedged LP P&L."""
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    cal=cfg["calibration"]; sample=cfg["sample"]; pos=cfg["position"]
    hcfg=cfg["hedge"]
    if not hcfg.get("venue") or str(hcfg.get("venue")).startswith("TO_FREEZE") or hcfg.get("expected_funding_interval_hours") is None or hcfg.get("taker_cost_bps") is None:
        raise RuntimeError("Choose/freeze the hedge venue, funding interval, and transaction-cost assumption before v0.15 power calibration.")
    ref_cfg=sample["primary_alignment"]
    swaps=candidate_events[candidate_events["event"].eq("Swap")].copy()
    aligned=align_reference(swaps,candidate_reference,float(ref_cfg["max_age_seconds"]),0)
    aligned=aligned[aligned["ref_mid"].notna()].copy()
    if len(aligned)<2:
        raise ValueError("candidate window has insufficient aligned swaps")
    start=pd.Timestamp(aligned["timestamp"].min()); end=pd.Timestamp(aligned["timestamp"].max())
    duration_days=max((end-start).total_seconds()/86400.0,1/86400)

    bench_window, bench_ann=time_weighted_apy_return(benchmark_rates,start,end)
    rv=daily_realized_variance(candidate_reference,sampling_minutes=int(cal["regimes"]["sampling_minutes"]))
    mean_ann_var=float(rv.mean())

    power_col="excess_return_inc"
    if power_col not in calibration_excess_increments:
        raise ValueError(f"calibration increments require `{power_col}`")
    p_cfg=cal["power"]
    method=str(p_cfg.get("stationary_bootstrap_block_method","calibration_autocorrelation"))
    if method != "calibration_autocorrelation":
        raise ValueError(f"unsupported stationary bootstrap block method: {method}")
    selected_mean_block=estimate_mean_block_length(
        calibration_excess_increments[power_col].to_numpy(),
        minimum=int(p_cfg.get("stationary_bootstrap_min_mean_block_swaps",5)),
        maximum=int(p_cfg.get("stationary_bootstrap_max_mean_block_swaps",1000)),
    )
    common=dict(
        calibration_excess_return_increments=calibration_excess_increments[power_col].to_numpy(),
        sample_observations=len(aligned), sample_duration_days=duration_days,
        economic_hurdle_annual_excess_return=float(cfg["benchmark"]["annual_excess_return_hurdle"]),
        mean_block_length=float(selected_mean_block),
        confidence_level=float(p_cfg["confidence_level"]),
        outer_reps=int(p_cfg["outer_reps"]), inner_bootstrap_reps=int(p_cfg["inner_bootstrap_reps"]),
    )
    detect_power=prospective_power(
        **common,true_annual_excess_return=float(p_cfg["detectability_alternative_annual_excess_return"]),seed=17
    )
    full_power=prospective_power(
        **common,true_annual_excess_return=float(p_cfg["full_go_power_alternative_annual_excess_return"]),seed=19
    )

    r_cfg=cal["regimes"]
    regimes=check_regime_coverage(
        calibration_reference,candidate_reference,
        lower_quantile=float(r_cfg["lower_quantile"]),upper_quantile=float(r_cfg["upper_quantile"]),
        min_days_each=int(r_cfg["minimum_days_each"]),sampling_minutes=int(r_cfg["sampling_minutes"]),
    )

    g_cfg=cal["gate0"]
    if g_cfg.get("annual_variable_cost_yield_assumption") is None or g_cfg.get("annual_fixed_cost_usd") is None:
        raise RuntimeError("Fill outcome-blind Gate-0 variable and fixed cost assumptions before calibration.")
    gate=gate0_from_tape(
        aligned,hypothetical_capital_usd=float(g_cfg["hypothetical_capital_usd"]),
        lower_multiplier=float(g_cfg["lower_multiplier"]),upper_multiplier=float(g_cfg["upper_multiplier"]),
        nominal_swap_fee_rate=float(cfg["pool"]["fee_tier_pips"])/1_000_000.0,
        mean_annualized_variance=mean_ann_var,benchmark_annual_yield=bench_ann,
        annual_variable_cost_yield=float(g_cfg["annual_variable_cost_yield_assumption"]),
        annual_fixed_cost_usd=float(g_cfg["annual_fixed_cost_usd"]),
        economic_hurdle_excess_yield=float(g_cfg["economic_hurdle_annual_excess_return"]),
        token0_decimals=int(cfg["pool"]["token0_decimals"]),token1_decimals=int(cfg["pool"]["token1_decimals"]),
    )

    cap_rows=[]
    for c in cfg["capacity"]["capital_usd"]:
        r=gate0_from_tape(
            aligned,hypothetical_capital_usd=float(c),lower_multiplier=float(g_cfg["lower_multiplier"]),
            upper_multiplier=float(g_cfg["upper_multiplier"]),nominal_swap_fee_rate=float(cfg["pool"]["fee_tier_pips"])/1_000_000.0,
            mean_annualized_variance=mean_ann_var,benchmark_annual_yield=bench_ann,
            annual_variable_cost_yield=float(g_cfg["annual_variable_cost_yield_assumption"]),
            annual_fixed_cost_usd=float(g_cfg["annual_fixed_cost_usd"]),economic_hurdle_excess_yield=float(g_cfg["economic_hurdle_annual_excess_return"]),
            token0_decimals=int(cfg["pool"]["token0_decimals"]),token1_decimals=int(cfg["pool"]["token1_decimals"]),
        )
        cap_rows.append({
            "capital_usd":float(c),"net_excess_yield_after_fixed":r.net_excess_yield_after_fixed,
            "expected_annual_excess_profit_usd":float(c)*r.net_excess_yield_after_fixed,
            "passes_economic_screen":r.passes_economic_screen,
        })
    capacity=pd.DataFrame(cap_rows)
    viable=capacity[capacity["passes_economic_screen"]]
    max_prize=float(viable["expected_annual_excess_profit_usd"].max()) if not viable.empty else float("-inf")
    capacity_pass=max_prize>=float(cfg["capacity"]["minimum_expected_annual_excess_profit_usd"])

    jit_events=candidate_events.copy()
    ref_keys=aligned[["block_number","log_index","ref_mid"]].drop_duplicates(["block_number","log_index"])
    jit_events=jit_events.merge(ref_keys,on=["block_number","log_index"],how="left")
    _,jit=jit_dilution_diagnostic(jit_events,int(cal["jit"]["max_lifetime_blocks"]))
    stat_power_pass=detect_power.statistical_power>=float(p_cfg["minimum_statistical_power"])
    full_power_pass=full_power.full_go_power>=float(p_cfg["minimum_full_go_power"])
    status="PASS" if all([stat_power_pass,full_power_pass,regimes.passes,gate.passes_economic_screen,capacity_pass]) else "FAIL"
    result={
        "status":status,"experiment_id":cfg["experiment_id"],"draft_spec_sha256":canonical_hash(cfg),"calibration_basis_sha256":calibration_basis_hash(cfg),
        "candidate_window":{"start":start.isoformat(),"end":end.isoformat(),"duration_days":duration_days,"aligned_swaps":int(len(aligned))},
        "benchmark":{"window_return":bench_window,"annualized_return":bench_ann},
        "realized_variance":{"mean_annualized_variance":mean_ann_var},
        "bootstrap":{"method":method,"selected_mean_block_swaps":float(selected_mean_block)},
        "power":{"detectability_at_5pct":detect_power.as_dict(),"full_go_material_alternative":full_power.as_dict(),"statistical_power_pass":stat_power_pass,"full_go_power_pass":full_power_pass},
        "regime_coverage":regimes.as_dict(),"gate0":gate.as_dict(),"jit":jit.as_dict(),
        "capacity":{"passes":capacity_pass,"max_expected_annual_excess_profit_usd":max_prize,"minimum_required_usd":float(cfg["capacity"]["minimum_expected_annual_excess_profit_usd"])},
        "notes":[
            "No primary exact hedged LP P&L is computed by v0.15 calibration.",
            "JIT is diagnostic only and pool events do not uniquely identify economic NFT positions.",
            "A PASS permits filling the primary dates/hedge venue and moving the spec to READY_TO_FREEZE; it is not evidence that LP edge exists."
        ]
    }
    write_frame(capacity,out/"capacity_napkin.csv")
    (out/"calibration_report.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result
