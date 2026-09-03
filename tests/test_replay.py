from houseedge.demo import synthetic_tape
from houseedge.research.alignment import align_reference
from houseedge.research.replay import replay_discrete_hedged_lp


def test_replay_runs_and_reconciles():
    swaps,ref=synthetic_tape(n=800)
    a=align_reference(swaps,ref,tolerance_seconds=1)
    path,s=replay_discrete_hedged_lp(
        a,capital_usd=10000,lower_multiplier=.8,upper_multiplier=1.2,
        swap_fee_rate=.0005,lp_fee_fraction=.75,delta_band_usd=250,
        hedge_taker_cost_bps=2,annualized_funding_rate=0,fixed_operating_cost_usd=2,
        token0_decimals=18,token1_decimals=6,
    )
    assert len(path)>100
    assert abs(path["net_pnl_inc_usd"].sum()-s.net_hedged_pnl_usd)<1e-6
