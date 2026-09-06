import numpy as np
from houseedge.research.power import prospective_power


def test_power_reports_structural_hurdle_warning():
    rng=np.random.default_rng(1)
    x=rng.normal(0,1e-6,500)
    r=prospective_power(x,sample_observations=500,sample_duration_days=90,true_annual_excess_return=.05,economic_hurdle_annual_excess_return=.05,mean_block_length=10,outer_reps=30,inner_bootstrap_reps=30)
    assert r.warning is not None
    assert 0<=r.statistical_power<=1
    assert 0<=r.full_go_power<=1
