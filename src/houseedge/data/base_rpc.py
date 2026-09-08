from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
from typing import Any


def utc_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def window_timestamps(start_value, end_value) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Interpret date-only end values as inclusive through 23:59:59.999999 UTC."""
    start = utc_timestamp(start_value)
    end = utc_timestamp(end_value)
    text = str(end_value)
    if "T" not in text and " " not in text:
        end = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    if end <= start:
        raise ValueError("window end must be after start")
    return start, end


def block_timestamp(w3: Any, block_number: int) -> pd.Timestamp:
    b = w3.eth.get_block(int(block_number))
    return pd.Timestamp(int(b["timestamp"]), unit="s", tz="UTC")


def block_at_or_after(w3: Any, when) -> int:
    """Binary-search the first canonical block whose timestamp is >= `when`."""
    target = int(utc_timestamp(when).timestamp())
    lo, hi = 0, int(w3.eth.block_number)
    while lo < hi:
        mid = (lo + hi) // 2
        ts = int(w3.eth.get_block(mid)["timestamp"])
        if ts < target:
            lo = mid + 1
        else:
            hi = mid
    return int(lo)


def block_at_or_before(w3: Any, when) -> int:
    """Binary-search the last canonical block whose timestamp is <= `when`."""
    target = int(utc_timestamp(when).timestamp())
    lo, hi = 0, int(w3.eth.block_number)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        ts = int(w3.eth.get_block(mid)["timestamp"])
        if ts <= target:
            lo = mid
        else:
            hi = mid - 1
    return int(lo)


def attach_block_timestamps(w3: Any, rows: list[dict], workers: int = 12) -> list[dict]:
    blocks = sorted({int(r["block_number"]) for r in rows})
    if not blocks:
        return rows
    mapping: dict[int, pd.Timestamp] = {}
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        futs = {ex.submit(block_timestamp, w3, b): b for b in blocks}
        for fut in as_completed(futs):
            b = futs[fut]
            mapping[b] = fut.result()
    for row in rows:
        row["timestamp"] = mapping[int(row["block_number"])]
    return rows
