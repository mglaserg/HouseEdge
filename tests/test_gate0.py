from houseedge.research.gate0 import gate0

def test_gate0_math():
    r=gate0(annualized_vol=.60,daily_volume_usd=25_000_000,active_capital_usd=100_000_000,lp_fee_rate=.000375)
    assert abs(r.frictionless_lvr_bound-.045)<1e-12
    assert r.annual_fee_yield>0
