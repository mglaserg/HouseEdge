from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from houseedge.config import (
    assert_reference_policy_selected,
    calibration_basis_hash,
    canonical_hash,
    reference_policy_hash,
)
from houseedge.research.alignment import align_reference
from houseedge.research.benchmark import time_weighted_apy_return
from houseedge.research.gate0 import Gate0Result, gate0_from_tape
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
    assert_reference_policy_selected(cfg)
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
        minimum=int(p_cfg.get("stationary_bootstrap_min_mean_block_days",5)),
        maximum=int(p_cfg.get("stationary_bootstrap_max_mean_block_days",1000)),
    )
    common=dict(
        calibration_excess_return_increments=calibration_excess_increments[power_col].to_numpy(),
        sample_observations=max(int(pd.to_datetime(aligned["timestamp"],utc=True).dt.floor("D").nunique()),2), sample_duration_days=duration_days,
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
        "status":status,"experiment_id":cfg["experiment_id"],"draft_spec_sha256":canonical_hash(cfg),"calibration_basis_sha256":calibration_basis_hash(cfg),"reference_policy_sha256":reference_policy_hash(cfg),
        "candidate_window":{"start":start.isoformat(),"end":end.isoformat(),"duration_days":duration_days,"aligned_swaps":int(len(aligned))},
        "benchmark":{"window_return":bench_window,"annualized_return":bench_ann},
        "realized_variance":{"mean_annualized_variance":mean_ann_var},
        "bootstrap":{"method":method,"selected_mean_block_days":float(selected_mean_block)},
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


def _iter_event_parts(path: str | Path):
    p=Path(path)
    if p.is_dir():
        parts=sorted(p.glob("part-*.parquet"))
    else:
        parts=[p]
    if not parts:
        raise FileNotFoundError(f"No parquet event parts found under {p}")
    for part in parts:
        frame=pd.read_parquet(part)
        if "timestamp" in frame:
            frame["timestamp"]=pd.to_datetime(frame["timestamp"],utc=True)
        yield part,frame


def _stream_short_lived_jit_map(candidate_events_path: str | Path, max_lifetime_blocks: int):
    """Build only the short-lived liquidity map; never materialize all events."""
    from collections import defaultdict, deque
    queues=defaultdict(deque)
    by_block=defaultdict(list)
    matched_liquidity=0.0
    for _,events in _iter_event_parts(candidate_events_path):
        x=events[events["event"].isin(["Mint","Burn"])].sort_values(["block_number","transaction_index","log_index"])
        for row in x.itertuples(index=False):
            key=(str(row.owner).lower(),int(row.tick_lower),int(row.tick_upper))
            amt=abs(float(row.liquidity_delta))
            if row.event=="Mint":
                queues[key].append([int(row.block_number),amt])
            else:
                remaining=amt
                while remaining>0 and queues[key]:
                    mint_block,open_amt=queues[key][0]
                    used=min(remaining,open_amt)
                    burn_block=int(row.block_number)
                    lifetime=burn_block-int(mint_block)
                    if lifetime<=int(max_lifetime_blocks):
                        matched_liquidity += float(used)
                        for b in range(int(mint_block),burn_block+1):
                            by_block[b].append((key[1],key[2],float(used)))
                    remaining-=used; open_amt-=used
                    if open_amt<=0:
                        queues[key].popleft()
                    else:
                        queues[key][0][1]=open_amt
    return by_block,float(matched_liquidity)


class _GateAccumulator:
    def __init__(self, capital_usd: float, cfg: dict, mean_ann_var: float, benchmark_ann: float):
        from houseedge.amm.v3_math import liquidity_for_capital
        self.capital=float(capital_usd); self.cfg=cfg; self.mean_ann_var=float(mean_ann_var); self.benchmark_ann=float(benchmark_ann)
        self.initialized=False; self.L=0.0; self.lower=0.0; self.upper=0.0
        self.fee_usd=0.0; self.gamma_weighted=0.0; self.gamma_seconds=0.0
        self.prev_ts=None; self.prev_gamma=None; self.first_ts=None; self.last_ts=None
        self._liq_for_capital=liquidity_for_capital

    def consume(self,row):
        from houseedge.research.gate0 import _numerical_gamma_usd
        g=self.cfg["calibration"]["gate0"]; pool=self.cfg["pool"]
        ts=pd.Timestamp(row.timestamp); price=float(row.ref_mid)
        if not self.initialized:
            self.lower=price*float(g["lower_multiplier"]); self.upper=price*float(g["upper_multiplier"])
            self.L=self._liq_for_capital(self.capital,price,self.lower,self.upper,int(pool["token0_decimals"]),int(pool["token1_decimals"]))
            self.first_ts=ts; self.initialized=True
        if self.prev_ts is not None and self.prev_gamma is not None:
            dt=max((ts-self.prev_ts).total_seconds(),0.0)
            self.gamma_weighted += self.prev_gamma*dt
            self.gamma_seconds += dt
        current_gamma=None
        if self.lower < price < self.upper:
            if float(row.amount0)>0:
                input_usd=float(row.amount0)*price
            elif float(row.amount1)>0:
                input_usd=float(row.amount1)
            else:
                input_usd=0.0
            if input_usd>0:
                lp_fraction=float(getattr(row,"lp_fee_fraction",1.0))
                active=max(float(row.liquidity),0.0)
                fee=float(pool["fee_tier_pips"])/1_000_000.0
                if active+self.L>0:
                    self.fee_usd += input_usd*fee*lp_fraction*(self.L/(active+self.L))
            gamma=_numerical_gamma_usd(self.L,price,self.lower,self.upper,int(pool["token0_decimals"]),int(pool["token1_decimals"]))
            current_gamma=max(0.0,-0.5*gamma*price*price*self.mean_ann_var)
        self.prev_gamma=current_gamma; self.prev_ts=ts; self.last_ts=ts

    def result(self):
        from houseedge.research.gate0 import Gate0Result
        if not self.initialized or self.first_ts is None or self.last_ts is None:
            raise RuntimeError("Gate-0 stream contained no aligned swaps")
        g=self.cfg["calibration"]["gate0"]
        duration_days=max((self.last_ts-self.first_ts).total_seconds()/86400.0,1/86400)
        annual_fee=(self.fee_usd/self.capital)*(365.0/duration_days)
        annual_lvr_usd=self.gamma_weighted/self.gamma_seconds if self.gamma_seconds>0 else 0.0
        annual_lvr=annual_lvr_usd/self.capital
        variable=float(g["annual_variable_cost_yield_assumption"]); fixed=float(g["annual_fixed_cost_usd"]); hurdle=float(g["economic_hurdle_annual_excess_return"])
        pre=annual_fee-annual_lvr-self.benchmark_ann-variable
        net=pre-fixed/self.capital
        margin=pre-hurdle
        min_cap=fixed/margin if fixed>0 and margin>0 else (0.0 if fixed<=0 and margin>0 else None)
        return Gate0Result(float(annual_fee),float(annual_lvr),self.benchmark_ann,variable,float(pre),fixed,self.capital,float(net),None if min_cap is None else float(min_cap),bool(net>=hurdle))


def run_design_calibration_from_paths(
    *, calibration_excess_increments_path: str | Path, calibration_reference_path: str | Path,
    candidate_reference_path: str | Path, candidate_events_path: str | Path,
    benchmark_rates_path: str | Path, cfg: dict, output_dir: str | Path,
) -> dict:
    """Bounded-memory v0.15 calibration for partitioned candidate event history."""
    assert_reference_policy_selected(cfg)
    from houseedge.data.reference import normalize_reference
    from houseedge.data.storage import read_frame
    from houseedge.research.jit import JITSummary

    cal_inc=read_frame(calibration_excess_increments_path)
    cal_ref=read_frame(calibration_reference_path)
    cand_ref=normalize_reference(read_frame(candidate_reference_path))
    bench=read_frame(benchmark_rates_path)
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    cal=cfg["calibration"]; p_cfg=cal["power"]

    # Outcome-blind reference-only quantities.
    rv=daily_realized_variance(cand_ref,sampling_minutes=int(cal["regimes"]["sampling_minutes"]))
    mean_ann_var=float(rv.mean())
    regimes=check_regime_coverage(cal_ref,cand_ref,lower_quantile=float(cal["regimes"]["lower_quantile"]),upper_quantile=float(cal["regimes"]["upper_quantile"]),min_days_each=int(cal["regimes"]["minimum_days_each"]),sampling_minutes=int(cal["regimes"]["sampling_minutes"]))

    # JIT lots are identified in a bounded-memory first pass.
    jit_by_block,matched_jit_liq=_stream_short_lived_jit_map(candidate_events_path,int(cal["jit"]["max_lifetime_blocks"]))

    align_cfg=cfg["sample"]["primary_alignment"]; tol=float(align_cfg["max_age_seconds"])
    ref_align=cand_ref[cand_ref.get("alignment_eligible",True).fillna(True).astype(bool)].copy() if "alignment_eligible" in cand_ref else cand_ref.copy()
    total_swaps=0; matched_swaps=0; days=set()
    jit_total=0; jit_swaps=0; jit_share_sum=0.0; jit_fee_num=0.0; jit_fee_den=0.0
    first_aligned=None; last_aligned=None

    # First candidate pass: resolve the exact aligned sample boundaries/counts without
    # computing LP P&L.  This keeps the benchmark interval and power horizon honest.
    for _,events in _iter_event_parts(candidate_events_path):
        swaps=events[events["event"].eq("Swap")].copy()
        if swaps.empty: continue
        total_swaps += len(swaps)
        lo=pd.Timestamp(swaps["timestamp"].min())-pd.Timedelta(seconds=tol); hi=pd.Timestamp(swaps["timestamp"].max())
        rp=ref_align[(ref_align["timestamp"]>=lo)&(ref_align["timestamp"]<=hi)].copy()
        aligned=align_reference(swaps,rp,tol,0)
        matched=aligned["ref_mid"].notna(); matched_swaps += int(matched.sum())
        aligned=aligned[matched].sort_values(["timestamp","block_number","log_index"])
        if aligned.empty: continue
        if first_aligned is None: first_aligned=pd.Timestamp(aligned["timestamp"].iloc[0])
        last_aligned=pd.Timestamp(aligned["timestamp"].iloc[-1])
        days.update(pd.to_datetime(aligned["timestamp"],utc=True).dt.floor("D").tolist())
    if first_aligned is None or last_aligned is None:
        raise RuntimeError("Candidate window has insufficient aligned swaps")
    missing_fraction=1.0-matched_swaps/max(total_swaps,1)
    if missing_fraction>float(cfg["validity"]["max_missing_reference_fraction"]):
        raise RuntimeError(f"Candidate reference alignment failed tolerance: missing_fraction={missing_fraction:.6f}")
    bench_window,bench_ann=time_weighted_apy_return(bench,first_aligned,last_aligned)

    capitals=sorted(set([float(cal["gate0"]["hypothetical_capital_usd"])] + [float(x) for x in cfg["capacity"]["capital_usd"]]))
    gates={c:_GateAccumulator(c,cfg,mean_ann_var,bench_ann) for c in capitals}

    # Second candidate pass: outcome-blind Gate-0 and JIT diagnostics only.
    for _,events in _iter_event_parts(candidate_events_path):
        swaps=events[events["event"].eq("Swap")].copy()
        if swaps.empty: continue
        lo=pd.Timestamp(swaps["timestamp"].min())-pd.Timedelta(seconds=tol); hi=pd.Timestamp(swaps["timestamp"].max())
        rp=ref_align[(ref_align["timestamp"]>=lo)&(ref_align["timestamp"]<=hi)].copy()
        aligned=align_reference(swaps,rp,tol,0)
        aligned=aligned[aligned["ref_mid"].notna()].sort_values(["timestamp","block_number","log_index"])
        for row in aligned.itertuples(index=False):
            for acc in gates.values(): acc.consume(row)
            lots=jit_by_block.get(int(row.block_number),())
            jit=sum(liq for tl,tu,liq in lots if tl<=int(row.tick)<tu)
            share=(jit/max(float(row.liquidity),1e-300)) if float(row.liquidity)>0 else 0.0
            share=min(max(share,0.0),1.0)
            jit_total += 1; jit_share_sum += share; jit_swaps += int(jit>0)
            if float(row.amount0)>0: inp=float(row.amount0)*float(row.ref_mid)
            elif float(row.amount1)>0: inp=float(row.amount1)
            else: inp=0.0
            if inp>0: jit_fee_num += inp*share; jit_fee_den += inp
    duration_days=max((last_aligned-first_aligned).total_seconds()/86400.0,1/86400)

    power_col="excess_return_inc"
    if power_col not in cal_inc: raise ValueError(f"calibration increments require `{power_col}`")
    method=str(p_cfg.get("stationary_bootstrap_block_method","calibration_autocorrelation"))
    selected_mean_block=estimate_mean_block_length(cal_inc[power_col].to_numpy(),minimum=int(p_cfg.get("stationary_bootstrap_min_mean_block_days",2)),maximum=int(p_cfg.get("stationary_bootstrap_max_mean_block_days",60)))
    common=dict(calibration_excess_return_increments=cal_inc[power_col].to_numpy(),sample_observations=max(len(days),2),sample_duration_days=duration_days,economic_hurdle_annual_excess_return=float(cfg["benchmark"]["annual_excess_return_hurdle"]),mean_block_length=float(selected_mean_block),confidence_level=float(p_cfg["confidence_level"]),outer_reps=int(p_cfg["outer_reps"]),inner_bootstrap_reps=int(p_cfg["inner_bootstrap_reps"]))
    detect_power=prospective_power(**common,true_annual_excess_return=float(p_cfg["detectability_alternative_annual_excess_return"]),seed=17)
    full_power=prospective_power(**common,true_annual_excess_return=float(p_cfg["full_go_power_alternative_annual_excess_return"]),seed=19)

    gate=gates[float(cal["gate0"]["hypothetical_capital_usd"])].result()
    cap_rows=[]
    for c in cfg["capacity"]["capital_usd"]:
        r=gates[float(c)].result(); cap_rows.append({"capital_usd":float(c),"net_excess_yield_after_fixed":r.net_excess_yield_after_fixed,"expected_annual_excess_profit_usd":float(c)*r.net_excess_yield_after_fixed,"passes_economic_screen":r.passes_economic_screen})
    capacity=pd.DataFrame(cap_rows); viable=capacity[capacity["passes_economic_screen"]]
    max_prize=float(viable["expected_annual_excess_profit_usd"].max()) if not viable.empty else float("-inf")
    capacity_pass=max_prize>=float(cfg["capacity"]["minimum_expected_annual_excess_profit_usd"])
    jit=JITSummary(matched_short_lived_liquidity=matched_jit_liq,swaps_with_jit_liquidity=int(jit_swaps),total_swaps=int(jit_total),fraction_swaps_with_jit=jit_swaps/max(jit_total,1),mean_jit_share_of_active_liquidity=jit_share_sum/max(jit_total,1),estimated_fraction_swap_fees_to_jit=(jit_fee_num/jit_fee_den if jit_fee_den>0 else None))
    stat_power_pass=detect_power.statistical_power>=float(p_cfg["minimum_statistical_power"]); full_power_pass=full_power.full_go_power>=float(p_cfg["minimum_full_go_power"])
    status="PASS" if all([stat_power_pass,full_power_pass,regimes.passes,gate.passes_economic_screen,capacity_pass]) else "FAIL"
    result={"status":status,"experiment_id":cfg["experiment_id"],"draft_spec_sha256":canonical_hash(cfg),"calibration_basis_sha256":calibration_basis_hash(cfg),"reference_policy_sha256":reference_policy_hash(cfg),"candidate_window":{"start":first_aligned.isoformat(),"end":last_aligned.isoformat(),"duration_days":duration_days,"aligned_swaps":int(matched_swaps),"daily_observations":int(len(days))},"benchmark":{"window_return":bench_window,"annualized_return":bench_ann},"realized_variance":{"mean_annualized_variance":mean_ann_var},"bootstrap":{"method":method,"selected_mean_block_days":float(selected_mean_block)},"power":{"detectability_at_5pct":detect_power.as_dict(),"full_go_material_alternative":full_power.as_dict(),"statistical_power_pass":stat_power_pass,"full_go_power_pass":full_power_pass},"regime_coverage":regimes.as_dict(),"gate0":gate.as_dict(),"jit":jit.as_dict(),"capacity":{"passes":capacity_pass,"max_expected_annual_excess_profit_usd":max_prize,"minimum_required_usd":float(cfg["capacity"]["minimum_expected_annual_excess_profit_usd"])},"notes":["No primary exact hedged LP P&L is computed by v0.15 calibration.","Calibration power and primary inference use dependent UTC daily P&L increments, not raw swap count.","Candidate event history is processed partition-by-partition to bound memory.","A PASS permits freezing the primary design; it is not evidence that LP edge exists."]}
    write_frame(capacity,out/"capacity_napkin.csv"); (out/"calibration_report.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result
