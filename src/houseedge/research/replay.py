from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import numpy as np
import pandas as pd

from houseedge.amm.v3_math import liquidity_for_capital, position_amounts


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


def _fee_usd(row, fee_rate: float, lp_fee_fraction: float, our_liquidity: float, active_liquidity: float, in_range: bool, boundary_cross: bool, boundary_policy: str) -> float:
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
    total_lp_fee=input_usd*fee_rate*lp_fee_fraction
    denom=max(float(active_liquidity),0.0)+our_liquidity
    return total_lp_fee*(our_liquidity/denom) if denom>0 else 0.0


def replay_discrete_hedged_lp(
    aligned_swaps: pd.DataFrame,
    *,
    capital_usd: float,
    lower_multiplier: float,
    upper_multiplier: float,
    swap_fee_rate: float,
    lp_fee_fraction: float,
    delta_band_usd: float,
    hedge_taker_cost_bps: float,
    annualized_funding_rate: float,
    fixed_operating_cost_usd: float,
    boundary_cross_fee_policy: str = "zero",
    token0_decimals: int = 18,
    token1_decimals: int = 6,
) -> tuple[pd.DataFrame, ReplaySummary]:
    x=aligned_swaps.dropna(subset=["ref_mid"]).copy().sort_values(["timestamp","block_number","log_index"]).reset_index(drop=True)
    if len(x)<2:
        raise ValueError("need >=2 swaps with aligned reference prices")
    p0=float(x.iloc[0].ref_mid)
    lower=p0*lower_multiplier; upper=p0*upper_multiplier
    L=liquidity_for_capital(capital_usd,p0,lower,upper,token0_decimals,token1_decimals)
    a0_0,a1_0=position_amounts(L,p0,lower,upper,token0_decimals,token1_decimals)
    initial_value=a0_0*p0+a1_0

    hedge_units=-a0_0
    prev_price=p0
    prev_ts=pd.Timestamp(x.iloc[0].timestamp)
    prev_lp_value=initial_value
    cum_fee=0.0; cum_hedge_price=0.0; cum_funding=0.0; cum_cost=0.0
    hedge_trades=0; boundary_count=0
    prev_tick=int(x.iloc[0].tick)
    rows=[]

    fee_rate=swap_fee_rate
    for i,row in enumerate(x.itertuples(index=False)):
        price=float(row.ref_mid)
        ts=pd.Timestamp(row.timestamp)
        a0,a1=position_amounts(L,price,lower,upper,token0_decimals,token1_decimals)
        lp_value=a0*price+a1
        lp_inc=lp_value-prev_lp_value if i>0 else 0.0

        dt_years=max((ts-prev_ts).total_seconds(),0.0)/(365.0*24*3600)
        hedge_price_inc=hedge_units*(price-prev_price) if i>0 else 0.0
        funding_inc=(-hedge_units)*price*annualized_funding_rate*dt_years if i>0 else 0.0
        cum_hedge_price+=hedge_price_inc; cum_funding+=funding_inc

        current_tick=int(row.tick)
        # Range activity inferred from quote price for our hypothetical position.
        in_range=lower < price < upper
        prev_in_range=lower < prev_price < upper
        boundary_cross=(in_range != prev_in_range) if i>0 else False
        boundary_count += int(boundary_cross)
        active_liq=float(row.liquidity)
        fee_inc=_fee_usd(row, fee_rate, lp_fee_fraction, L, active_liq, in_range, boundary_cross, boundary_cross_fee_policy)
        cum_fee+=fee_inc

        target=-a0
        error_units=target-hedge_units
        band_units=delta_band_usd/max(price,1e-12)
        trade_units=0.0; trade_cost=0.0
        if abs(error_units)>band_units:
            new_hedge=target-math.copysign(band_units,error_units)
            trade_units=new_hedge-hedge_units
            trade_cost=abs(trade_units)*price*hedge_taker_cost_bps/1e4
            hedge_units=new_hedge
            cum_cost+=trade_cost
            hedge_trades+=1

        net_inc=lp_inc+fee_inc+hedge_price_inc+funding_inc-trade_cost
        rows.append({
            "timestamp":ts,"ref_mid":price,"lp_amount0":a0,"lp_amount1":a1,"lp_value_usd":lp_value,
            "lp_inventory_pnl_inc_usd":lp_inc,"fee_inc_usd":fee_inc,"hedge_units":hedge_units,
            "hedge_trade_units":trade_units,"hedge_price_pnl_inc_usd":hedge_price_inc,
            "funding_pnl_inc_usd":funding_inc,"hedge_cost_inc_usd":trade_cost,"net_pnl_inc_usd":net_inc,
            "in_range":in_range,"boundary_cross":boundary_cross,"active_liquidity":active_liq,
        })
        prev_price=price; prev_ts=ts; prev_lp_value=lp_value; prev_tick=current_tick

    path=pd.DataFrame(rows)
    if fixed_operating_cost_usd:
        path.loc[path.index[-1],"net_pnl_inc_usd"]-=fixed_operating_cost_usd
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
