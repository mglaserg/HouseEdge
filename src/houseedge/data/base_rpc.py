from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import time

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


def _provider_endpoint(w3: Any) -> str:
    provider = getattr(w3, "provider", None)
    return str(getattr(provider, "endpoint_uri", "") or "")


def probe_log_block_limit(
    w3: Any,
    address: str,
    requested_blocks: int = 10_000,
    candidates: tuple[int, ...] = (10_000, 5_000, 2_000, 1_000, 500, 100, 50, 10),
) -> int:
    """Probe provider eth_getLogs block-range support with a no-match topic.

    Returns the largest tested range accepted by the provider, capped at
    ``requested_blocks``. Fake/test Web3 objects without a provider are treated
    as unrestricted so offline unit tests do not make network calls.
    """
    provider = getattr(w3, "provider", None)
    if provider is None or not hasattr(provider, "make_request"):
        return int(requested_blocks)
    head = int(w3.eth.block_number)
    impossible_topic = "0x" + "00" * 32
    checked = []
    for n in candidates:
        n = min(int(n), int(requested_blocks))
        if n <= 0 or n in checked:
            continue
        checked.append(n)
        start = max(0, head - n + 1)
        params = [{
            "fromBlock": hex(start),
            "toBlock": hex(head),
            "address": address,
            "topics": [impossible_topic],
        }]
        try:
            resp = provider.make_request("eth_getLogs", params)
            if isinstance(resp, dict) and resp.get("error"):
                continue
            return n
        except Exception:
            continue
    raise RuntimeError(
        "RPC provider rejected even a 10-block eth_getLogs probe. "
        "Use a historical/log-capable Base RPC endpoint."
    )


def get_event_logs_resilient(
    event,
    *,
    from_block: int,
    to_block: int,
    argument_filters: dict | None = None,
    retries: int = 2,
):
    """Fetch contract-event logs with retry and recursive range splitting.

    This handles providers that intermittently reject large/result-heavy ranges.
    A persistent error on a single block is re-raised instead of hidden.
    """
    kwargs = {"from_block": int(from_block), "to_block": int(to_block)}
    if argument_filters:
        kwargs["argument_filters"] = argument_filters
    last_exc = None
    for attempt in range(int(retries) + 1):
        try:
            return list(event().get_logs(**kwargs))
        except Exception as exc:
            last_exc = exc
            if attempt < int(retries):
                time.sleep(0.25 * (2 ** attempt))
    if int(from_block) >= int(to_block):
        raise last_exc
    mid = (int(from_block) + int(to_block)) // 2
    left = get_event_logs_resilient(
        event, from_block=int(from_block), to_block=mid,
        argument_filters=argument_filters, retries=retries,
    )
    right = get_event_logs_resilient(
        event, from_block=mid + 1, to_block=int(to_block),
        argument_filters=argument_filters, retries=retries,
    )
    return left + right


def validate_historical_log_plan(
    w3: Any,
    address: str,
    *,
    requested_chunk_blocks: int,
    total_blocks: int,
) -> int:
    """Resolve an RPC-safe chunk size and reject impractical tiny-range plans."""
    supported = probe_log_block_limit(w3, address, requested_chunk_blocks)
    effective = min(int(requested_chunk_blocks), int(supported))
    if effective <= 10 and int(total_blocks) > 100_000:
        endpoint = _provider_endpoint(w3)
        provider_name = "Alchemy Free" if "alchemy.com" in endpoint else "this RPC provider"
        est_chunks = (int(total_blocks) + effective - 1) // effective
        raise RuntimeError(
            f"{provider_name} appears limited to {effective} blocks per eth_getLogs request. "
            f"The requested historical window spans about {int(total_blocks):,} blocks "
            f"(~{est_chunks:,} chunks per event type), which is not a practical backfill path. "
            "Use an Alchemy Pay-As-You-Go/other RPC with larger log ranges, or a bulk "
            "historical source such as Envio HyperSync. HouseEdge aborts before spending "
            "millions of RPC calls."
        )
    return effective
