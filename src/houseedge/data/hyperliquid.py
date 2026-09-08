from __future__ import annotations

import time
import httpx
import pandas as pd

INFO_URL = "https://api.hyperliquid.xyz/info"


def fetch_funding_history(coin: str, start, end, *, info_url: str = INFO_URL, client: httpx.Client | None = None) -> pd.DataFrame:
    """Fetch complete Hyperliquid historical funding rates with documented pagination."""
    start_ts = pd.Timestamp(start); end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is None: start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None: end_ts = end_ts.tz_localize("UTC")
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    owns = client is None
    c = client or httpx.Client(timeout=30.0)
    rows = []
    cursor = start_ms
    try:
        while cursor <= end_ms:
            r = c.post(info_url, json={"type":"fundingHistory","coin":coin,"startTime":cursor,"endTime":end_ms})
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for obj in batch:
                t = int(obj["time"])
                if t < start_ms or t > end_ms:
                    continue
                rows.append({
                    "timestamp": pd.Timestamp(t, unit="ms", tz="UTC"),
                    "funding_rate": float(obj["fundingRate"]),
                    "premium": float(obj["premium"]) if obj.get("premium") is not None else None,
                    "coin": str(obj.get("coin", coin)),
                    "source": "hyperliquid_fundingHistory",
                })
            last = max(int(x["time"]) for x in batch)
            if last < cursor:
                break
            cursor = last + 1
            if len(batch) < 500:
                break
            time.sleep(0.02)
    finally:
        if owns:
            c.close()
    if not rows:
        return pd.DataFrame(columns=["timestamp","funding_rate","premium","coin","source"])
    return pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
