from __future__ import annotations

import numpy as np


def stationary_bootstrap_sums(values, reps: int = 2000, mean_block_length: float = 100.0, seed: int = 11) -> np.ndarray:
    x=np.asarray(values,dtype=float)
    x=x[np.isfinite(x)]
    n=len(x)
    if n < 2:
        raise ValueError("need at least two observations")
    p=1.0/max(float(mean_block_length),1.0)
    rng=np.random.default_rng(seed)
    out=np.empty(reps)
    for b in range(reps):
        idx=rng.integers(0,n)
        total=0.0
        for _ in range(n):
            total+=x[idx]
            if rng.random()<p:
                idx=rng.integers(0,n)
            else:
                idx=(idx+1)%n
        out[b]=total
    return out


def ci(values, level: float = 0.95) -> tuple[float,float]:
    a=(1-level)/2
    return float(np.quantile(values,a)), float(np.quantile(values,1-a))
