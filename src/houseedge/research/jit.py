from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class JITSummary:
    matched_short_lived_liquidity: float
    swaps_with_jit_liquidity: int
    total_swaps: int
    fraction_swaps_with_jit: float
    mean_jit_share_of_active_liquidity: float
    estimated_fraction_swap_fees_to_jit: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def identify_short_lived_liquidity(events: pd.DataFrame, max_lifetime_blocks: int = 3) -> pd.DataFrame:
    """FIFO-match Mint/Burn lots by owner/range and flag short-lived liquidity.

    This is a diagnostic, not an economic-position identity resolver. Partial
    burns are matched FIFO. Exact NFT position identity is deliberately not
    inferred from pool events alone.
    """
    if events.empty:
        return pd.DataFrame(columns=["owner", "tick_lower", "tick_upper", "mint_block", "burn_block", "liquidity", "lifetime_blocks"])
    x = events[events["event"].isin(["Mint", "Burn"])].sort_values(["block_number", "transaction_index", "log_index"]).copy()
    queues: dict[tuple, deque] = defaultdict(deque)
    matches: list[dict] = []
    for row in x.itertuples(index=False):
        key = (str(row.owner).lower(), int(row.tick_lower), int(row.tick_upper))
        amt = abs(float(row.liquidity_delta))
        if row.event == "Mint":
            queues[key].append([int(row.block_number), amt])
        else:
            remaining = amt
            while remaining > 0 and queues[key]:
                mint_block, open_amt = queues[key][0]
                used = min(remaining, open_amt)
                lifetime = int(row.block_number) - int(mint_block)
                if lifetime <= int(max_lifetime_blocks):
                    matches.append({
                        "owner": key[0], "tick_lower": key[1], "tick_upper": key[2],
                        "mint_block": int(mint_block), "burn_block": int(row.block_number),
                        "liquidity": float(used), "lifetime_blocks": int(lifetime),
                    })
                remaining -= used
                open_amt -= used
                if open_amt <= 0:
                    queues[key].popleft()
                else:
                    queues[key][0][1] = open_amt
    return pd.DataFrame(matches)


def jit_dilution_diagnostic(events: pd.DataFrame, max_lifetime_blocks: int = 3) -> tuple[pd.DataFrame, JITSummary]:
    lots = identify_short_lived_liquidity(events, max_lifetime_blocks=max_lifetime_blocks)
    swaps = events[events["event"].eq("Swap")].copy().sort_values(["block_number", "transaction_index", "log_index"])
    if swaps.empty:
        return swaps.assign(jit_liquidity=0.0, jit_share_active=0.0), JITSummary(0.0, 0, 0, 0.0, 0.0, None)
    jit_vals = []
    for row in swaps.itertuples(index=False):
        if lots.empty:
            jit = 0.0
        else:
            mask = (
                (lots["mint_block"] <= int(row.block_number))
                & (lots["burn_block"] >= int(row.block_number))
                & (lots["tick_lower"] <= int(row.tick))
                & (int(row.tick) < lots["tick_upper"])
            )
            jit = float(lots.loc[mask, "liquidity"].sum())
        jit_vals.append(jit)
    swaps["jit_liquidity"] = jit_vals
    active = pd.to_numeric(swaps["liquidity"], errors="coerce").fillna(0.0)
    swaps["jit_share_active"] = (swaps["jit_liquidity"] / active.where(active > 0)).fillna(0.0).clip(lower=0.0, upper=1.0)
    n_jit = int((swaps["jit_liquidity"] > 0).sum())

    fee_fraction = None
    if "ref_mid" in swaps.columns and {"amount0","amount1"}.issubset(swaps.columns):
        ref=pd.to_numeric(swaps["ref_mid"],errors="coerce")
        a0=pd.to_numeric(swaps["amount0"],errors="coerce")
        a1=pd.to_numeric(swaps["amount1"],errors="coerce")
        input_usd=np.where(a0>0,a0*ref,np.where(a1>0,a1,np.nan))
        valid=np.isfinite(input_usd)&(input_usd>0)
        if valid.any():
            weights=np.asarray(input_usd,dtype=float)[valid]
            shares=swaps.loc[valid,"jit_share_active"].to_numpy(float)
            fee_fraction=float(np.sum(weights*shares)/np.sum(weights))

    summary = JITSummary(
        matched_short_lived_liquidity=float(lots["liquidity"].sum()) if not lots.empty else 0.0,
        swaps_with_jit_liquidity=n_jit,
        total_swaps=int(len(swaps)),
        fraction_swaps_with_jit=n_jit / float(len(swaps)),
        mean_jit_share_of_active_liquidity=float(swaps["jit_share_active"].mean()),
        estimated_fraction_swap_fees_to_jit=fee_fraction,
    )
    return swaps, summary
