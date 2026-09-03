from __future__ import annotations

import math

Q96 = 2**96


def sqrt_price_x96_to_price(sqrt_price_x96: int | float, decimals0: int, decimals1: int) -> float:
    """Return token1 per token0 in human units."""
    raw = (float(sqrt_price_x96) / Q96) ** 2
    return raw * 10 ** (decimals0 - decimals1)


def tick_to_raw_price(tick: int) -> float:
    return 1.0001 ** tick


def tick_to_price(tick: int, decimals0: int, decimals1: int) -> float:
    return tick_to_raw_price(tick) * 10 ** (decimals0 - decimals1)


def price_to_tick(price: float, decimals0: int, decimals1: int) -> int:
    raw = price / 10 ** (decimals0 - decimals1)
    return math.floor(math.log(raw) / math.log(1.0001))


def _human_to_raw_price(price: float, decimals0: int, decimals1: int) -> float:
    return price / 10 ** (decimals0 - decimals1)


def position_amounts(
    liquidity: float,
    price: float,
    lower: float,
    upper: float,
    decimals0: int = 18,
    decimals1: int = 6,
) -> tuple[float, float]:
    """Human token amounts for a Uniswap-v3 raw liquidity parameter L.

    Prices are human token1/token0 (e.g. USDC per WETH). Internally the v3
    formulas use raw token units, which makes the returned L directly comparable
    with the pool's on-chain `liquidity` field.
    """
    if not (liquidity >= 0 and price > 0 and 0 < lower < upper):
        raise ValueError("invalid liquidity/price/range")
    p = _human_to_raw_price(price, decimals0, decimals1)
    a = _human_to_raw_price(lower, decimals0, decimals1)
    b = _human_to_raw_price(upper, decimals0, decimals1)
    sp, sa, sb = map(math.sqrt, (p, a, b))
    if sp <= sa:
        amount0_raw = liquidity * (sb - sa) / (sa * sb)
        amount1_raw = 0.0
    elif sp >= sb:
        amount0_raw = 0.0
        amount1_raw = liquidity * (sb - sa)
    else:
        amount0_raw = liquidity * (sb - sp) / (sp * sb)
        amount1_raw = liquidity * (sp - sa)
    return amount0_raw / 10**decimals0, amount1_raw / 10**decimals1


def liquidity_for_capital(
    capital_usd: float,
    price: float,
    lower: float,
    upper: float,
    decimals0: int = 18,
    decimals1: int = 6,
) -> float:
    """Choose raw L so amount0*price + amount1 equals capital at inception."""
    a0, a1 = position_amounts(1.0, price, lower, upper, decimals0, decimals1)
    per_l = a0 * price + a1
    if per_l <= 0:
        raise ValueError("range produces zero value per unit liquidity")
    return capital_usd / per_l


def position_value(
    liquidity: float,
    price: float,
    lower: float,
    upper: float,
    decimals0: int = 18,
    decimals1: int = 6,
) -> float:
    a0, a1 = position_amounts(liquidity, price, lower, upper, decimals0, decimals1)
    return a0 * price + a1
