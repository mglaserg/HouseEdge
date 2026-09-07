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


def estimate_mean_block_length(
    values,
    *,
    minimum: int = 5,
    maximum: int = 1000,
) -> float:
    """Outcome-blind dependence-length heuristic for the stationary bootstrap.

    Uses an FFT autocorrelation estimate plus Geyer's initial-positive-sequence
    truncation.  The resulting integrated autocorrelation time is used as the
    mean stationary-bootstrap block length and clipped to preregistered bounds.

    This is deliberately a calibration rule, not a primary-outcome tuning knob.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 10:
        raise ValueError("need at least 10 observations to estimate block length")
    x = x - x.mean()
    var = float(np.dot(x, x) / len(x))
    if not np.isfinite(var) or var <= 0:
        return float(minimum)

    n = len(x)
    fft_n = 1 << (2 * n - 1).bit_length()
    fx = np.fft.rfft(x, n=fft_n)
    acov = np.fft.irfft(fx * np.conjugate(fx), n=fft_n)[:n]
    acov = acov / np.arange(n, 0, -1, dtype=float)
    acf = acov / acov[0]

    # Initial-positive-sequence truncation stabilizes the noisy long-lag tail.
    positive_sum = 0.0
    max_lag = min(n - 1, int(maximum) * 10)
    lag = 1
    while lag <= max_lag:
        if lag + 1 <= max_lag:
            pair = float(acf[lag] + acf[lag + 1])
            if not np.isfinite(pair) or pair <= 0:
                break
            positive_sum += pair
            lag += 2
        else:
            val = float(acf[lag])
            if not np.isfinite(val) or val <= 0:
                break
            positive_sum += val
            lag += 1

    tau = max(1.0, 1.0 + 2.0 * positive_sum)
    return float(np.clip(np.ceil(tau), int(minimum), int(maximum)))
