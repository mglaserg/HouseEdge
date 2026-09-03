import numpy as np
from houseedge.research.bootstrap import stationary_bootstrap_sums, ci

def test_stationary_bootstrap_shape():
    x=np.arange(100,dtype=float)
    b=stationary_bootstrap_sums(x,reps=50,mean_block_length=10)
    assert b.shape==(50,)
    lo,hi=ci(b)
    assert lo<hi
