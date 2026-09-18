import numpy as np
import pandas as pd

from houseedge.config import load_yaml, PoolSpec
from houseedge.demo import synthetic_tape
from houseedge.research.alignment import align_reference
from houseedge.research.replay import (
    replay_discrete_hedged_lp,
    replay_discrete_hedged_lp_chunk,
    finalize_streaming_replay,
)


def test_streaming_replay_matches_batch_exactly():
    swaps, ref = synthetic_tape(n=240)
    cfg=load_yaml("configs/experiment_001.yaml")
    spec=PoolSpec.from_config(cfg)
    aligned=align_reference(swaps,ref,3.0,0).dropna(subset=["ref_mid"])
    kw=dict(
        capital_usd=10_000.0,lower_multiplier=.8,upper_multiplier=1.2,
        swap_fee_rate=spec.fee_tier_pips/1_000_000.0,lp_fee_fraction=1.0,
        delta_band_fraction_nav=.05,hedge_to_zero=True,hedge_taker_cost_bps=5.0,
        funding_events=None,annualized_funding_rate=0.0,fixed_operating_cost_usd=0.0,
        charge_initial_and_final_hedge_costs=True,boundary_cross_fee_policy="zero",
        token0_decimals=18,token1_decimals=6,
    )
    batch,_=replay_discrete_hedged_lp(aligned,**kw)
    state=None; pieces=[]
    chunk_kw={k:v for k,v in kw.items() if k!="fixed_operating_cost_usd"}
    for chunk in np.array_split(aligned,7):
        inc,state=replay_discrete_hedged_lp_chunk(chunk,state=state,**chunk_kw)
        pieces.append(inc)
    streamed=pd.concat(pieces,ignore_index=True)
    _,adjust=finalize_streaming_replay(state,hedge_taker_cost_bps=5.0,charge_initial_and_final_hedge_costs=True)
    streamed.loc[streamed.index[-1],"net_pnl_inc_usd"] += adjust
    np.testing.assert_allclose(streamed["net_pnl_inc_usd"],batch["net_pnl_inc_usd"],rtol=0,atol=1e-10)
