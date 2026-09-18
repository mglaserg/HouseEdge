from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np
import pandas as pd

from houseedge.amm.v3_math import liquidity_for_capital, position_amounts, sqrt_price_x96_to_price


@dataclass
class ReplaySummary:
    initial_capital_usd: float
    ending_lp_value_usd: float
    lp_inventory_pnl_usd: float
    fee_pnl_usd: float
    hedge_price_pnl_usd: float
    hedge_funding_pnl_usd: float
    hedge_trading_cost_usd: float
    fixed_operating_cost_usd: float
    net_hedged_pnl_usd: float
    net_hedged_return: float
    annualized_net_hedged_return: float
    hedged_sharpe: float
    hedge_trades: int
    swaps_used: int
    boundary_cross_swaps: int
    duration_days: float

    def as_dict(self):
        return asdict(self)


def _pool_price(row, token0_decimals: int, token1_decimals: int) -> float:
    sx = getattr(row, "sqrt_price_x96", None)
    if sx is not None and pd.notna(sx) and float(sx) > 0:
        return sqrt_price_x96_to_price(float(sx), token0_decimals, token1_decimals)
    return float(row.ref_mid)


def _fee_usd(
    row,
    fee_rate: float,
    default_lp_fee_fraction: float,
    our_liquidity: float,
    active_liquidity: float,
    in_range: bool,
    boundary_cross: bool,
    boundary_policy: str,
) -> float:
    if not in_range:
        return 0.0
    if boundary_cross and boundary_policy == "zero":
        return 0.0
    if row.amount0 > 0:
        input_usd=float(row.amount0)*float(row.ref_mid)
    elif row.amount1 > 0:
        input_usd=float(row.amount1)
    else:
        return 0.0
    row_fraction = getattr(row, "lp_fee_fraction", np.nan)
    lp_fraction = float(row_fraction) if pd.notna(row_fraction) else float(default_lp_fee_fraction)
    total_lp_fee=input_usd*fee_rate*lp_fraction
    denom=max(float(active_liquidity),0.0)+our_liquidity
    return total_lp_fee*(our_liquidity/denom) if denom>0 else 0.0


def _funding_for_interval(
    funding_events: pd.DataFrame | None,
    start: pd.Timestamp,
    end: pd.Timestamp,
    hedge_units: float,
    fallback_price: float,
) -> float:
    if funding_events is None or funding_events.empty or end <= start:
        return 0.0
    f = funding_events[(funding_events["timestamp"] > start) & (funding_events["timestamp"] <= end)]
    if f.empty:
        return 0.0
    pnl = 0.0
    for row in f.itertuples(index=False):
        price = float(getattr(row, "mark_price", fallback_price))
        rate = float(getattr(row, "funding_rate"))
        # Positive funding: longs pay shorts. Negative hedge_units therefore earns.
        pnl += -hedge_units * price * rate
    return float(pnl)


def replay_discrete_hedged_lp(
    aligned_swaps: pd.DataFrame,
    *,
    capital_usd: float,
    lower_multiplier: float,
    upper_multiplier: float,
    swap_fee_rate: float,
    lp_fee_fraction: float = 1.0,
    delta_band_usd: float | None = None,
    delta_band_fraction_nav: float | None = None,
    hedge_to_zero: bool = True,
    hedge_taker_cost_bps: float,
    funding_events: pd.DataFrame | None = None,
    annualized_funding_rate: float | None = None,
    fixed_operating_cost_usd: float,
    charge_initial_and_final_hedge_costs: bool = True,
    boundary_cross_fee_policy: str = "zero",
    token0_decimals: int = 18,
    token1_decimals: int = 6,
) -> tuple[pd.DataFrame, ReplaySummary]:
    x=aligned_swaps.dropna(subset=["ref_mid"]).copy().sort_values(["timestamp","block_number","log_index"]).reset_index(drop=True)
    if len(x)<2:
        raise ValueError("need >=2 swaps with aligned reference prices")
    if delta_band_fraction_nav is None and delta_band_usd is None:
        raise ValueError("provide delta_band_fraction_nav or delta_band_usd")
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    if funding_events is not None:
        funding_events = funding_events.copy()
        funding_events["timestamp"] = pd.to_datetime(funding_events["timestamp"], utc=True)
        if "funding_rate" not in funding_events:
            raise ValueError("funding events require funding_rate per payment interval")
        funding_events = funding_events.sort_values("timestamp")

    ref0=float(x.iloc[0].ref_mid)
    pool0=_pool_price(x.iloc[0],token0_decimals,token1_decimals)
    lower=pool0*lower_multiplier; upper=pool0*upper_multiplier
    L=liquidity_for_capital(capital_usd,ref0,lower,upper,token0_decimals,token1_decimals)
    a0_0,a1_0=position_amounts(L,pool0,lower,upper,token0_decimals,token1_decimals)
    initial_value=a0_0*ref0+a1_0

    hedge_units=-a0_0
    prev_ref=ref0
    prev_pool=pool0
    prev_ts=pd.Timestamp(x.iloc[0].timestamp)
    prev_lp_value=initial_value
    cum_fee=0.0; cum_hedge_price=0.0; cum_funding=0.0
    initial_cost = abs(hedge_units)*ref0*hedge_taker_cost_bps/1e4 if charge_initial_and_final_hedge_costs else 0.0
    cum_cost=initial_cost
    hedge_trades=1 if charge_initial_and_final_hedge_costs and abs(hedge_units)>0 else 0
    boundary_count=0
    rows=[]

    for i,row in enumerate(x.itertuples(index=False)):
        ref_price=float(row.ref_mid)
        pool_price=_pool_price(row,token0_decimals,token1_decimals)
        ts=pd.Timestamp(row.timestamp)
        a0,a1=position_amounts(L,pool_price,lower,upper,token0_decimals,token1_decimals)
        lp_value=a0*ref_price+a1
        lp_inc=lp_value-prev_lp_value if i>0 else 0.0

        hedge_price_inc=hedge_units*(ref_price-prev_ref) if i>0 else 0.0
        if i>0 and funding_events is not None:
            funding_inc=_funding_for_interval(funding_events,prev_ts,ts,hedge_units,ref_price)
        elif i>0 and annualized_funding_rate is not None:
            dt_years=max((ts-prev_ts).total_seconds(),0.0)/(365.0*24*3600)
            funding_inc=(-hedge_units)*ref_price*float(annualized_funding_rate)*dt_years
        else:
            funding_inc=0.0
        cum_hedge_price+=hedge_price_inc; cum_funding+=funding_inc

        in_range=lower < pool_price < upper
        prev_in_range=lower < prev_pool < upper
        boundary_cross=(in_range != prev_in_range) if i>0 else False
        boundary_count += int(boundary_cross)
        active_liq=float(row.liquidity)
        fee_inc=_fee_usd(row, swap_fee_rate, lp_fee_fraction, L, active_liq, in_range, boundary_cross, boundary_cross_fee_policy)
        cum_fee+=fee_inc

        target=-a0
        error_units=target-hedge_units
        band_usd = float(delta_band_fraction_nav)*max(lp_value,1e-12) if delta_band_fraction_nav is not None else float(delta_band_usd)
        error_notional=abs(error_units)*ref_price
        trade_units=0.0; trade_cost=0.0
        if error_notional>band_usd:
            if hedge_to_zero:
                new_hedge=target
            else:
                band_units=band_usd/max(ref_price,1e-12)
                new_hedge=target-math.copysign(band_units,error_units)
            trade_units=new_hedge-hedge_units
            trade_cost=abs(trade_units)*ref_price*hedge_taker_cost_bps/1e4
            hedge_units=new_hedge
            cum_cost+=trade_cost
            hedge_trades+=1

        net_inc=lp_inc+fee_inc+hedge_price_inc+funding_inc-trade_cost
        if i == 0 and initial_cost:
            net_inc -= initial_cost
        rows.append({
            "timestamp":ts,"ref_mid":ref_price,"pool_price":pool_price,"lp_amount0":a0,"lp_amount1":a1,"lp_value_usd":lp_value,
            "lp_inventory_pnl_inc_usd":lp_inc,"fee_inc_usd":fee_inc,"hedge_units":hedge_units,
            "hedge_trade_units":trade_units,"hedge_price_pnl_inc_usd":hedge_price_inc,
            "funding_pnl_inc_usd":funding_inc,"hedge_cost_inc_usd":trade_cost + (initial_cost if i==0 else 0.0),"net_pnl_inc_usd":net_inc,
            "in_range":in_range,"boundary_cross":boundary_cross,"active_liquidity":active_liq,
        })
        prev_ref=ref_price; prev_pool=pool_price; prev_ts=ts; prev_lp_value=lp_value

    # Liquidate the hedge at the end so window P&L includes the full round trip.
    final_close_cost=abs(hedge_units)*prev_ref*hedge_taker_cost_bps/1e4 if charge_initial_and_final_hedge_costs else 0.0
    if final_close_cost:
        cum_cost += final_close_cost
        hedge_trades += 1
        rows[-1]["hedge_cost_inc_usd"] += final_close_cost
        rows[-1]["net_pnl_inc_usd"] -= final_close_cost
    if fixed_operating_cost_usd:
        rows[-1]["net_pnl_inc_usd"]-=fixed_operating_cost_usd

    path=pd.DataFrame(rows)
    path["cum_net_pnl_usd"]=path["net_pnl_inc_usd"].cumsum()
    path["cum_fee_usd"]=path["fee_inc_usd"].cumsum()

    ending_lp=float(path.iloc[-1].lp_value_usd)
    lp_inventory=ending_lp-initial_value
    net=lp_inventory+cum_fee+cum_hedge_price+cum_funding-cum_cost-fixed_operating_cost_usd
    duration_days=max((pd.Timestamp(path.iloc[-1].timestamp)-pd.Timestamp(path.iloc[0].timestamp)).total_seconds()/86400,1/86400)
    ret=net/initial_value
    ann=(1+ret)**(365.0/duration_days)-1 if ret>-1 else -1.0
    daily=path.set_index("timestamp")["net_pnl_inc_usd"].resample("1D").sum()/initial_value
    sharpe=float(np.sqrt(365)*daily.mean()/daily.std(ddof=1)) if len(daily)>1 and daily.std(ddof=1)>0 else float("nan")
    summary=ReplaySummary(initial_value,ending_lp,lp_inventory,cum_fee,cum_hedge_price,cum_funding,cum_cost,fixed_operating_cost_usd,net,ret,ann,sharpe,hedge_trades,len(path),boundary_count,duration_days)
    return path,summary


@dataclass
class StreamingReplayState:
    """Carry exact discrete-hedge LP state across partitioned event chunks."""
    initialized: bool = False
    lower: float = 0.0
    upper: float = 0.0
    liquidity: float = 0.0
    initial_value: float = 0.0
    hedge_units: float = 0.0
    prev_ref: float = 0.0
    prev_pool: float = 0.0
    prev_ts: pd.Timestamp | None = None
    prev_lp_value: float = 0.0
    swaps_used: int = 0
    last_ts: pd.Timestamp | None = None


def replay_discrete_hedged_lp_chunk(
    aligned_swaps: pd.DataFrame,
    *,
    state: StreamingReplayState | None = None,
    capital_usd: float,
    lower_multiplier: float,
    upper_multiplier: float,
    swap_fee_rate: float,
    lp_fee_fraction: float = 1.0,
    delta_band_usd: float | None = None,
    delta_band_fraction_nav: float | None = None,
    hedge_to_zero: bool = True,
    hedge_taker_cost_bps: float,
    funding_events: pd.DataFrame | None = None,
    annualized_funding_rate: float | None = None,
    charge_initial_and_final_hedge_costs: bool = True,
    boundary_cross_fee_policy: str = "zero",
    token0_decimals: int = 18,
    token1_decimals: int = 6,
) -> tuple[pd.DataFrame, StreamingReplayState]:
    """Replay one aligned swap chunk while preserving state across chunks.

    No final hedge liquidation is charged here. Call
    :func:`finalize_streaming_replay` once after the last chunk.
    """
    st = state or StreamingReplayState()
    x = aligned_swaps.dropna(subset=["ref_mid"]).copy()
    if x.empty:
        return pd.DataFrame(columns=["timestamp", "net_pnl_inc_usd"]), st
    x = x.sort_values(["timestamp", "block_number", "log_index"]).reset_index(drop=True)
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    if delta_band_fraction_nav is None and delta_band_usd is None:
        raise ValueError("provide delta_band_fraction_nav or delta_band_usd")
    if funding_events is not None:
        funding_events = funding_events.copy()
        funding_events["timestamp"] = pd.to_datetime(funding_events["timestamp"], utc=True)
        if "funding_rate" not in funding_events:
            raise ValueError("funding events require funding_rate per payment interval")
        funding_events = funding_events.sort_values("timestamp")

    rows=[]
    for row in x.itertuples(index=False):
        ref_price=float(row.ref_mid)
        pool_price=_pool_price(row,token0_decimals,token1_decimals)
        ts=pd.Timestamp(row.timestamp)
        first_global = not st.initialized
        if first_global:
            st.lower=pool_price*lower_multiplier
            st.upper=pool_price*upper_multiplier
            st.liquidity=liquidity_for_capital(capital_usd,ref_price,st.lower,st.upper,token0_decimals,token1_decimals)
            a0_0,a1_0=position_amounts(st.liquidity,pool_price,st.lower,st.upper,token0_decimals,token1_decimals)
            st.initial_value=a0_0*ref_price+a1_0
            st.hedge_units=-a0_0
            st.prev_ref=ref_price
            st.prev_pool=pool_price
            st.prev_ts=ts
            st.prev_lp_value=st.initial_value
            st.initialized=True

        a0,a1=position_amounts(st.liquidity,pool_price,st.lower,st.upper,token0_decimals,token1_decimals)
        lp_value=a0*ref_price+a1
        lp_inc=0.0 if first_global else lp_value-st.prev_lp_value
        hedge_price_inc=0.0 if first_global else st.hedge_units*(ref_price-st.prev_ref)
        if not first_global and funding_events is not None:
            funding_inc=_funding_for_interval(funding_events,st.prev_ts,ts,st.hedge_units,ref_price)
        elif not first_global and annualized_funding_rate is not None:
            dt_years=max((ts-st.prev_ts).total_seconds(),0.0)/(365.0*24*3600)
            funding_inc=(-st.hedge_units)*ref_price*float(annualized_funding_rate)*dt_years
        else:
            funding_inc=0.0

        in_range=st.lower < pool_price < st.upper
        prev_in_range=st.lower < st.prev_pool < st.upper
        boundary_cross=(in_range != prev_in_range) if not first_global else False
        active_liq=float(row.liquidity)
        fee_inc=_fee_usd(row, swap_fee_rate, lp_fee_fraction, st.liquidity, active_liq, in_range, boundary_cross, boundary_cross_fee_policy)

        target=-a0
        error_units=target-st.hedge_units
        band_usd = float(delta_band_fraction_nav)*max(lp_value,1e-12) if delta_band_fraction_nav is not None else float(delta_band_usd)
        trade_units=0.0; trade_cost=0.0
        if abs(error_units)*ref_price > band_usd:
            if hedge_to_zero:
                new_hedge=target
            else:
                band_units=band_usd/max(ref_price,1e-12)
                new_hedge=target-math.copysign(band_units,error_units)
            trade_units=new_hedge-st.hedge_units
            trade_cost=abs(trade_units)*ref_price*hedge_taker_cost_bps/1e4
            st.hedge_units=new_hedge

        initial_cost=0.0
        if first_global and charge_initial_and_final_hedge_costs:
            initial_cost=abs(st.hedge_units)*ref_price*hedge_taker_cost_bps/1e4
        net_inc=lp_inc+fee_inc+hedge_price_inc+funding_inc-trade_cost-initial_cost
        rows.append({"timestamp":ts,"net_pnl_inc_usd":net_inc})

        st.prev_ref=ref_price
        st.prev_pool=pool_price
        st.prev_ts=ts
        st.prev_lp_value=lp_value
        st.last_ts=ts
        st.swaps_used += 1
    return pd.DataFrame(rows), st


def finalize_streaming_replay(
    state: StreamingReplayState,
    *,
    hedge_taker_cost_bps: float,
    charge_initial_and_final_hedge_costs: bool = True,
    fixed_operating_cost_usd: float = 0.0,
) -> tuple[pd.Timestamp, float]:
    """Return the final close/fixed-cost adjustment for a streaming replay."""
    if not state.initialized or state.last_ts is None:
        raise ValueError("cannot finalize an empty streaming replay")
    adjustment = -float(fixed_operating_cost_usd)
    if charge_initial_and_final_hedge_costs:
        adjustment -= abs(state.hedge_units)*state.prev_ref*hedge_taker_cost_bps/1e4
    return state.last_ts, float(adjustment)
