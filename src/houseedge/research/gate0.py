from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np
import pandas as pd

from houseedge.amm.v3_math import liquidity_for_capital, position_value


@dataclass(frozen=True)
class Gate0Result:
    annual_fee_yield: float
    annual_lvr_estimate: float
    benchmark_annual_yield: float
    annual_variable_cost_yield: float
    pre_fixed_excess_yield: float
    annual_fixed_cost_usd: float
    hypothetical_capital_usd: float
    net_excess_yield_after_fixed: float
    minimum_viable_capital_usd: float | None
    passes_economic_screen: bool

    def as_dict(self):
        return asdict(self)


def _numerical_gamma_usd(liquidity: float, price: float, lower: float, upper: float, decimals0: int, decimals1: int) -> float:
    # Stable central difference in human-price coordinates.
    h = max(price * 1e-4, 1e-6)
    vm = position_value(liquidity, max(price-h, 1e-12), lower, upper, decimals0, decimals1)
    v0 = position_value(liquidity, price, lower, upper, decimals0, decimals1)
    vp = position_value(liquidity, price+h, lower, upper, decimals0, decimals1)
    return (vp - 2*v0 + vm) / (h*h)


def gate0_from_tape(
    swaps: pd.DataFrame,
    *,
    hypothetical_capital_usd: float,
    lower_multiplier: float,
    upper_multiplier: float,
    nominal_swap_fee_rate: float,
    mean_annualized_variance: float,
    benchmark_annual_yield: float = 0.0,
    annual_variable_cost_yield: float = 0.0,
    annual_fixed_cost_usd: float = 0.0,
    economic_hurdle_excess_yield: float = 0.05,
    token0_decimals: int = 18,
    token1_decimals: int = 6,
) -> Gate0Result:
    """Outcome-blind Gate 0 on a consistent hypothetical active-liquidity basis.

    Fee capture is computed swap-by-swap using the hypothetical position's raw
    Uniswap liquidity against contemporaneous active pool liquidity. LVR is a
    local gamma/variance approximation for the *same hypothetical position*, so
    fees and predictable loss share the same capital/range denominator.
    """
    x=swaps.copy()
    if "ref_mid" not in x:
        raise ValueError("Gate-0 tape requires ref_mid")
    x=x.dropna(subset=["ref_mid","liquidity","timestamp"]).sort_values("timestamp")
    if len(x)<2:
        raise ValueError("Gate-0 tape needs at least two swaps")
    p0=float(x.iloc[0].ref_mid)
    lower=p0*float(lower_multiplier); upper=p0*float(upper_multiplier)
    L=liquidity_for_capital(hypothetical_capital_usd,p0,lower,upper,token0_decimals,token1_decimals)
    fee_usd=0.0
    gamma_rates=[]
    gamma_times=[]
    rows=list(x.itertuples(index=False))
    for j,row in enumerate(rows):
        price=float(row.ref_mid)
        if not (lower < price < upper):
            continue
        if float(row.amount0)>0:
            input_usd=float(row.amount0)*price
        elif float(row.amount1)>0:
            input_usd=float(row.amount1)
        else:
            continue
        lp_fraction=float(getattr(row,"lp_fee_fraction",1.0))
        active=max(float(row.liquidity),0.0)
        fee_usd += input_usd*nominal_swap_fee_rate*lp_fraction*(L/(active+L)) if active+L>0 else 0.0
        gamma=_numerical_gamma_usd(L,price,lower,upper,token0_decimals,token1_decimals)
        # Predictable-loss rate for dP/P volatility sigma: -1/2 Gamma P^2 sigma^2.
        gamma_rates.append(max(0.0,-0.5*gamma*price*price*mean_annualized_variance))
        if j < len(rows)-1:
            gamma_times.append(max((pd.Timestamp(rows[j+1].timestamp)-pd.Timestamp(row.timestamp)).total_seconds(),0.0))
        else:
            gamma_times.append(0.0)
    duration_seconds=max((pd.Timestamp(x.iloc[-1].timestamp)-pd.Timestamp(x.iloc[0].timestamp)).total_seconds(),1.0)
    duration_days=duration_seconds/86400.0
    annual_fee_yield=(fee_usd/hypothetical_capital_usd)*(365.0/duration_days)
    annual_lvr_usd=float(np.average(gamma_rates,weights=gamma_times)) if gamma_rates and sum(gamma_times)>0 else (float(np.mean(gamma_rates)) if gamma_rates else 0.0)
    annual_lvr_yield=annual_lvr_usd/hypothetical_capital_usd
    pre_fixed=annual_fee_yield-annual_lvr_yield-benchmark_annual_yield-annual_variable_cost_yield
    net_after_fixed=pre_fixed-(annual_fixed_cost_usd/hypothetical_capital_usd)
    margin_before_fixed=pre_fixed-economic_hurdle_excess_yield
    min_cap=(annual_fixed_cost_usd/margin_before_fixed) if annual_fixed_cost_usd>0 and margin_before_fixed>0 else (0.0 if annual_fixed_cost_usd<=0 and margin_before_fixed>0 else None)
    return Gate0Result(
        float(annual_fee_yield),float(annual_lvr_yield),float(benchmark_annual_yield),float(annual_variable_cost_yield),float(pre_fixed),
        float(annual_fixed_cost_usd),float(hypothetical_capital_usd),float(net_after_fixed),
        None if min_cap is None else float(min_cap),bool(net_after_fixed>=economic_hurdle_excess_yield),
    )


def gate0(*, annualized_vol: float, daily_volume_usd: float, active_capital_usd: float, lp_fee_rate: float):
    """Deprecated scalar screen retained for compatibility with v0.1 demos."""
    if annualized_vol < 0 or daily_volume_usd < 0 or active_capital_usd <= 0 or not (0 <= lp_fee_rate < 1):
        raise ValueError("invalid Gate-0 inputs")
    annual_turnover=(daily_volume_usd/active_capital_usd)*365.0
    fee_yield=lp_fee_rate*annual_turnover
    lvr=(annualized_vol**2)/8.0
    edge=fee_yield-lvr
    @dataclass(frozen=True)
    class LegacyGate0Result:
        annual_fee_yield: float
        frictionless_lvr_bound: float
        rough_edge: float
        passes_conservative_screen: bool
        def as_dict(self): return asdict(self)
    return LegacyGate0Result(fee_yield,lvr,edge,edge>0)
