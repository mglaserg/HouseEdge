from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Gate0Result:
    annual_fee_yield: float
    frictionless_lvr_bound: float
    rough_edge: float
    passes_conservative_screen: bool

    def as_dict(self):
        return asdict(self)


def gate0(*, annualized_vol: float, daily_volume_usd: float, active_capital_usd: float, lp_fee_rate: float) -> Gate0Result:
    """Cheap conservative screen.

    LVR sigma^2/8 is a frictionless full-range benchmark, not calibrated realized LVR.
    Fee yield is based on active capital, not total TVL.
    """
    if annualized_vol < 0 or daily_volume_usd < 0 or active_capital_usd <= 0 or not (0 <= lp_fee_rate < 1):
        raise ValueError("invalid Gate-0 inputs")
    annual_turnover=(daily_volume_usd/active_capital_usd)*365.0
    fee_yield=lp_fee_rate*annual_turnover
    lvr=(annualized_vol**2)/8.0
    edge=fee_yield-lvr
    return Gate0Result(fee_yield,lvr,edge,edge>0)
