from __future__ import annotations
import pandas as pd
from houseedge.research.replay import replay_discrete_hedged_lp


def capacity_sweep(aligned_swaps: pd.DataFrame, capitals: list[float], replay_kwargs: dict) -> pd.DataFrame:
    rows=[]
    for c in capitals:
        _, s = replay_discrete_hedged_lp(aligned_swaps, capital_usd=float(c), **replay_kwargs)
        rows.append({
            "capital_usd": float(c),
            "net_pnl_usd": s.net_hedged_pnl_usd,
            "net_return": s.net_hedged_return,
            "annualized_net_return": s.annualized_net_hedged_return,
            "hedged_sharpe": s.hedged_sharpe,
            "hedge_trades": s.hedge_trades,
            "boundary_cross_swaps": s.boundary_cross_swaps,
            "capacity_label": "passive_counterfactual_capacity",
        })
    return pd.DataFrame(rows)
