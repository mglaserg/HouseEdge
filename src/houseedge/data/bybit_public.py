from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd

from houseedge.data.binance_public import _download, _epoch_us, _month_starts

BASE_URL = "https://public.bybit.com/spot"
REQUIRED_COLUMNS = {"timestamp", "price"}


def _archive_url(
    symbol: str,
    month: pd.Timestamp,
    *,
    base_url: str = BASE_URL,
) -> str:
    symbol = symbol.upper()
    return f"{base_url.rstrip('/')}/{symbol}/{symbol}-{month:%Y-%m}.csv.gz"


def download_spot_archive(
    symbol: str,
    month: pd.Timestamp,
    cache_dir: str | Path,
    *,
    force: bool = False,
    base_url: str = BASE_URL,
) -> Path:
    url = _archive_url(symbol, month, base_url=base_url)
    dest = Path(cache_dir) / Path(url).name
    return _download(url, dest, force=force)


def _read_gzip_chunks(path: Path, chunksize: int = 500_000):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        for chunk in pd.read_csv(stream, chunksize=chunksize, low_memory=False):
            missing = REQUIRED_COLUMNS.difference(chunk.columns)
            if missing:
                raise ValueError(f"Bybit archive {path} is missing columns: {sorted(missing)}")
            yield chunk


def load_last_trades_for_targets(
    symbol: str,
    target_timestamps,
    cache_dir: str | Path,
    *,
    max_age_seconds: float,
    force: bool = False,
    base_url: str = BASE_URL,
) -> pd.DataFrame:
    """Return the last Bybit spot trade at or before each target.

    The official monthly archives are scanned once and reduced to sparse target
    matches. No later trade can be selected, and stale matches are discarded.
    """
    targets = (
        pd.Series(pd.to_datetime(pd.Series(target_timestamps), utc=True).dropna().unique())
        .sort_values()
        .reset_index(drop=True)
    )
    columns = [
        "target_timestamp",
        "timestamp",
        "mid",
        "last_trade",
        "age_seconds",
        "source",
        "alignment_eligible",
        "regime_eligible",
    ]
    if targets.empty:
        return pd.DataFrame(columns=columns)

    target_us = _epoch_us(targets)
    result_time = np.full(len(targets), -1, dtype=np.int64)
    result_price = np.full(len(targets), np.nan, dtype=float)
    cursor = 0
    carry_t: int | None = None
    carry_p: float | None = None

    start = targets.iloc[0] - pd.Timedelta(seconds=float(max_age_seconds))
    for month in _month_starts(start, targets.iloc[-1]):
        path = download_spot_archive(
            symbol,
            month,
            cache_dir,
            force=force,
            base_url=base_url,
        )
        for chunk in _read_gzip_chunks(path):
            raw = pd.to_numeric(chunk["timestamp"], errors="coerce")
            price = pd.to_numeric(chunk["price"], errors="coerce")
            valid = raw.notna() & price.notna()
            if not valid.any():
                continue
            values = raw[valid].astype("int64").to_numpy()
            # Bybit spot archives use Unix milliseconds. Keep a defensive
            # microsecond branch so a future archive migration is explicit.
            trade_us = values if float(np.median(values)) >= 1e14 else values * 1000
            trade_price = price[valid].astype(float).to_numpy()
            if carry_t is not None and trade_us[0] > carry_t:
                trade_us = np.concatenate([[carry_t], trade_us])
                trade_price = np.concatenate([[carry_p], trade_price])
            upper = int(np.searchsorted(target_us, int(trade_us[-1]), side="right"))
            if upper > cursor:
                target_slice = target_us[cursor:upper]
                indices = np.searchsorted(trade_us, target_slice, side="right") - 1
                valid_indices = indices >= 0
                destinations = np.arange(cursor, upper)[valid_indices]
                result_time[destinations] = trade_us[indices[valid_indices]]
                result_price[destinations] = trade_price[indices[valid_indices]]
                cursor = upper
            carry_t = int(trade_us[-1])
            carry_p = float(trade_price[-1])

        month_end_us = int(
            (month + pd.offsets.MonthBegin(1)).to_datetime64().astype("datetime64[us]").astype(np.int64)
        ) - 1
        upper = int(np.searchsorted(target_us, month_end_us, side="right"))
        if carry_t is not None and upper > cursor:
            destinations = np.arange(cursor, upper)
            result_time[destinations] = carry_t
            result_price[destinations] = carry_p
            cursor = upper

    age = (target_us - result_time) / 1_000_000.0
    eligible = (
        (result_time >= 0)
        & np.isfinite(result_price)
        & (age >= 0)
        & (age <= float(max_age_seconds))
    )
    out = pd.DataFrame(
        {
            "target_timestamp": targets[eligible].to_numpy(),
            "timestamp": pd.to_datetime(result_time[eligible], unit="us", utc=True),
            "mid": result_price[eligible],
            "last_trade": result_price[eligible],
            "age_seconds": age[eligible],
            "source": "bybit_spot_trade",
            "alignment_eligible": True,
            "regime_eligible": False,
        }
    )
    if (out["timestamp"] > out["target_timestamp"]).any():
        raise RuntimeError("Bybit reference construction selected a future trade")
    return out.sort_values(["target_timestamp", "timestamp"]).reset_index(drop=True)
