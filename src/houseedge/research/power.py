from __future__ import annotations

from dataclasses import dataclass, asdict
import numpy as np

from houseedge.research.bootstrap import stationary_bootstrap_sums, ci


@dataclass(frozen=True)
class PowerResult:
    true_annual_excess_return: float
    economic_hurdle_annual_excess_return: float
    statistical_power: float
    full_go_power: float
    outer_reps: int
    inner_bootstrap_reps: int
    confidence_level: float
    warning: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _stationary_resample(values: np.ndarray, n: int, mean_block_length: float, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / max(float(mean_block_length), 1.0)
    out = np.empty(n, dtype=float)
    idx = int(rng.integers(0, len(values)))
    for i in range(n):
        out[i] = values[idx]
        if rng.random() < p:
            idx = int(rng.integers(0, len(values)))
        else:
            idx = (idx + 1) % len(values)
    return out


def prospective_power(
    calibration_excess_return_increments,
    *,
    sample_observations: int,
    sample_duration_days: float,
    true_annual_excess_return: float = 0.05,
    economic_hurdle_annual_excess_return: float = 0.05,
    mean_block_length: float = 100.0,
    confidence_level: float = 0.95,
    outer_reps: int = 300,
    inner_bootstrap_reps: int = 300,
    seed: int = 17,
) -> PowerResult:
    """Prospective power using only a separate calibration return process.

    Calibration increments should be *excess-return* increments after the cash
    benchmark. Their mean is removed so only the observed dependence/noise
    structure is reused. A deterministic drift corresponding to the assumed
    true annual excess return is injected into each synthetic primary sample.
    """
    x = np.asarray(calibration_excess_return_increments, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 10:
        raise ValueError("need at least 10 calibration increments")
    if sample_observations < 2 or sample_duration_days <= 0:
        raise ValueError("invalid prospective sample size/duration")
    noise = x - x.mean()
    rng = np.random.default_rng(seed)
    target_window_return = (1.0 + true_annual_excess_return) ** (sample_duration_days / 365.0) - 1.0
    drift_per_obs = target_window_return / sample_observations
    statistical_passes = 0
    full_passes = 0
    annual_factor = 365.0 / sample_duration_days
    for _ in range(int(outer_reps)):
        sim = _stationary_resample(noise, sample_observations, mean_block_length, rng) + drift_per_obs
        point_window = float(sim.sum())
        point_ann = (1.0 + point_window) ** annual_factor - 1.0 if point_window > -1 else -1.0
        boot = stationary_bootstrap_sums(
            sim,
            reps=int(inner_bootstrap_reps),
            mean_block_length=mean_block_length,
            seed=int(rng.integers(0, 2**31 - 1)),
        )
        boot_ann = np.where(boot > -1, (1.0 + boot) ** annual_factor - 1.0, -1.0)
        lower, _ = ci(boot_ann, confidence_level)
        stat = lower > 0
        statistical_passes += int(stat)
        full_passes += int(stat and point_ann >= economic_hurdle_annual_excess_return)
    warning = None
    if true_annual_excess_return <= economic_hurdle_annual_excess_return:
        warning = (
            "The assumed true edge is at or below the point-estimate economic hurdle. "
            "Full GO power is structurally capped near 50% for an unbiased estimator; "
            "use statistical_power for detectability at this edge or test full GO power at a larger material alternative."
        )
    return PowerResult(
        float(true_annual_excess_return),
        float(economic_hurdle_annual_excess_return),
        statistical_passes / float(outer_reps),
        full_passes / float(outer_reps),
        int(outer_reps),
        int(inner_bootstrap_reps),
        float(confidence_level),
        warning,
    )
