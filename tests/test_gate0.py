from houseedge.research.gate0 import gate0

def test_gate0_math():
    r=gate0(annualized_vol=.60,daily_volume_usd=25_000_000,active_capital_usd=100_000_000,lp_fee_rate=.000375)
    assert abs(r.frictionless_lvr_bound-.045)<1e-12
    assert r.annual_fee_yield>0

import pandas as pd
from houseedge.demo import synthetic_tape
from houseedge.research.alignment import align_reference
from houseedge.research.gate0 import gate0_from_tape


def test_gate0_tape_uses_variance_and_costs():
    swaps,ref=synthetic_tape(n=300)
    a=align_reference(swaps,ref,tolerance_seconds=1)
    a["lp_fee_fraction"]=0.75
    r=gate0_from_tape(
        a,
        hypothetical_capital_usd=10_000,
        lower_multiplier=.8,
        upper_multiplier=1.2,
        nominal_swap_fee_rate=.0005,
        mean_annualized_variance=.36,
        benchmark_annual_yield=.04,
        annual_variable_cost_yield=.01,
        annual_fixed_cost_usd=100,
        economic_hurdle_excess_yield=.05,
    )
    assert r.annual_lvr_estimate>0
    assert r.annual_variable_cost_yield==.01
    assert r.net_excess_yield_after_fixed < r.pre_fixed_excess_yield
