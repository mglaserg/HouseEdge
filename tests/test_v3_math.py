import math
from houseedge.amm.v3_math import liquidity_for_capital, position_amounts, sqrt_price_x96_to_price


def test_sqrt_price_round_trip_human_units():
    price=3500.0
    raw=price/10**12
    sx=math.sqrt(raw)*(2**96)
    assert abs(sqrt_price_x96_to_price(sx,18,6)/price-1)<1e-12


def test_liquidity_matches_capital_and_is_raw_scale():
    L=liquidity_for_capital(10000,3500,2800,4200,18,6)
    a0,a1=position_amounts(L,3500,2800,4200,18,6)
    assert abs(a0*3500+a1-10000)<1e-6
    assert L>1e10
