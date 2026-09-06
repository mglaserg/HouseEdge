from __future__ import annotations

from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RegimeCoverage:
    lower_variance_threshold: float
    upper_variance_threshold: float
    low_days: int
    high_days: int
    total_days: int
    min_days_each: int
    passes: bool

    def as_dict(self) -> dict:
        return asdict(self)


def daily_realized_variance(reference: pd.DataFrame, sampling_minutes: int = 5) -> pd.Series:
    """Annualized daily realized variance from outcome-blind ETH reference prices."""
    if "timestamp" not in reference or "mid" not in reference:
        raise ValueError("reference requires timestamp and mid")
    x = reference[["timestamp", "mid"]].copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    x["mid"] = pd.to_numeric(x["mid"])
    x = x.dropna().sort_values("timestamp").set_index("timestamp")
    sampled = x["mid"].resample(f"{int(sampling_minutes)}min").last().dropna()
    lr = np.log(sampled).diff()
    daily = lr.pow(2).resample("1D").sum(min_count=2) * 365.0
    return daily.dropna()


def check_regime_coverage(
    calibration_reference: pd.DataFrame,
    candidate_reference: pd.DataFrame,
    *,
    lower_quantile: float = 0.20,
    upper_quantile: float = 0.80,
    min_days_each: int = 5,
    sampling_minutes: int = 5,
) -> RegimeCoverage:
    cal = daily_realized_variance(calibration_reference, sampling_minutes=sampling_minutes)
    cand = daily_realized_variance(candidate_reference, sampling_minutes=sampling_minutes)
    if len(cal) < 20:
        raise ValueError("calibration period needs at least 20 daily realized-variance observations")
    lo = float(cal.quantile(lower_quantile))
    hi = float(cal.quantile(upper_quantile))
    low_days = int((cand <= lo).sum())
    high_days = int((cand >= hi).sum())
    return RegimeCoverage(lo, hi, low_days, high_days, int(len(cand)), int(min_days_each), low_days >= min_days_each and high_days >= min_days_each)
