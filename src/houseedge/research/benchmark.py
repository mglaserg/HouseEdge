from __future__ import annotations

import math
import pandas as pd


def time_weighted_apy_return(
    rates: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    apy_column: str = "apy",
) -> tuple[float, float]:
    """Integrate a piecewise-constant annual APY series over [start, end].

    Returns (window_return, annualized_return). APY values are fractions, e.g.
    0.045 for 4.5%. The last observation at or before `start` is required so
    the benchmark is defined from the beginning of the strategy window.
    """
    if end <= start:
        raise ValueError("benchmark end must be after start")
    x = rates.copy()
    if "timestamp" not in x or apy_column not in x:
        raise ValueError("benchmark requires timestamp and APY columns")
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    x[apy_column] = pd.to_numeric(x[apy_column])
    x = x.sort_values("timestamp").dropna(subset=[apy_column])
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    prior = x[x["timestamp"] <= start].tail(1)
    if prior.empty:
        raise ValueError("benchmark has no observation at or before strategy start")
    within = x[(x["timestamp"] > start) & (x["timestamp"] < end)]
    points = pd.concat([prior, within], ignore_index=True)
    # The prior observation supplies the rate effective at `start`; do not accrue
    # from the prior observation timestamp itself.
    points.loc[0, "timestamp"] = start
    timestamps = list(points["timestamp"]) + [end]
    log_growth = 0.0
    for i, row in points.iterrows():
        dt_years = (timestamps[i + 1] - timestamps[i]).total_seconds() / (365.0 * 24 * 3600)
        apy = float(row[apy_column])
        if apy <= -1:
            raise ValueError("APY must be > -100%")
        log_growth += math.log1p(apy) * dt_years
    window_return = math.expm1(log_growth)
    years = (end - start).total_seconds() / (365.0 * 24 * 3600)
    annualized = math.expm1(math.log1p(window_return) / years)
    return float(window_return), float(annualized)
