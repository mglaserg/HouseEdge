from __future__ import annotations

import pandas as pd


def pack_fee_protocol(token0_denominator: int, token1_denominator: int) -> int:
    """Pack Uniswap v3 protocol fee denominators into slot0.feeProtocol."""
    if not (0 <= token0_denominator <= 15 and 0 <= token1_denominator <= 15):
        raise ValueError("protocol fee denominators must fit uint4")
    return int(token0_denominator) | (int(token1_denominator) << 4)


def unpack_fee_protocol(packed: int) -> tuple[int, int]:
    packed = int(packed)
    return packed & 0x0F, (packed >> 4) & 0x0F


def lp_fee_fraction_for_swap(packed: int, amount0: float, amount1: float) -> float:
    """Return the fraction of the nominal swap fee retained by LPs.

    In Uniswap v3, the low nibble applies when token0 is the swap input
    (amount0 > 0), while the high nibble applies when token1 is the input.
    A zero denominator means protocol fees are disabled for that input token.
    """
    p0, p1 = unpack_fee_protocol(packed)
    if amount0 > 0:
        denom = p0
    elif amount1 > 0:
        denom = p1
    else:
        return 1.0
    return 1.0 if denom == 0 else 1.0 - 1.0 / float(denom)


def attach_protocol_fee_state(events: pd.DataFrame, initial_fee_protocol: int) -> pd.DataFrame:
    """Walk ordered pool events and attach historical protocol-fee state.

    `initial_fee_protocol` must be read from slot0 at the block immediately
    preceding the event window. SetFeeProtocol events update the state for
    subsequent logs. Swap rows receive an `lp_fee_fraction` column.
    """
    if events.empty:
        return events.copy()
    required = {"event", "block_number", "log_index"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"events missing required columns: {sorted(missing)}")
    order_cols = [c for c in ("block_number", "transaction_index", "log_index") if c in events.columns]
    x = events.sort_values(order_cols).copy().reset_index(drop=True)
    packed = int(initial_fee_protocol)
    packed_states: list[int] = []
    lp_fractions: list[float] = []
    for row in x.itertuples(index=False):
        event = str(row.event)
        if event == "SetFeeProtocol":
            p0_new = int(getattr(row, "fee_protocol0_new"))
            p1_new = int(getattr(row, "fee_protocol1_new"))
            packed = pack_fee_protocol(p0_new, p1_new)
        packed_states.append(packed)
        if event == "Swap":
            lp_fractions.append(
                lp_fee_fraction_for_swap(packed, float(getattr(row, "amount0")), float(getattr(row, "amount1")))
            )
        else:
            lp_fractions.append(float("nan"))
    x["fee_protocol_packed"] = packed_states
    x["lp_fee_fraction"] = lp_fractions
    return x
