import numpy as np
from houseedge.research.bootstrap import stationary_bootstrap_sums, ci

def test_stationary_bootstrap_shape():
    x=np.arange(100,dtype=float)
    b=stationary_bootstrap_sums(x,reps=50,mean_block_length=10)
    assert b.shape==(50,)
    lo,hi=ci(b)
    assert lo<hi

from houseedge.research.bootstrap import estimate_mean_block_length


def test_calibration_derived_block_length_detects_serial_dependence():
    rng=np.random.default_rng(123)
    iid=rng.normal(0,1,4000)
    serial=np.empty(4000)
    serial[0]=rng.normal()
    for i in range(1,len(serial)):
        serial[i]=0.9*serial[i-1]+rng.normal(scale=0.4)
    b_iid=estimate_mean_block_length(iid,minimum=5,maximum=1000)
    b_serial=estimate_mean_block_length(serial,minimum=5,maximum=1000)
    assert b_iid>=5
    assert b_serial>b_iid
