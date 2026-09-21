from __future__ import annotations

import hashlib
import io
from pathlib import Path
import zipfile

import httpx
import numpy as np
import pandas as pd

from houseedge.data.storage import write_frame

BASE_URL = "https://data.binance.vision"
AGG_COLUMNS = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "timestamp_raw", "buyer_is_maker", "best_match"]
KLINE_COLUMNS = ["open_time_raw", "open", "high", "low", "close", "volume", "close_time_raw", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def _month_starts(start, end) -> list[pd.Timestamp]:
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    if s.tzinfo is None: s = s.tz_localize("UTC")
    if e.tzinfo is None: e = e.tz_localize("UTC")
    s = pd.Timestamp(year=s.year, month=s.month, day=1, tz="UTC")
    e = pd.Timestamp(year=e.year, month=e.month, day=1, tz="UTC")
    return list(pd.date_range(s, e, freq="MS", tz="UTC"))


def _archive_url(kind: str, symbol: str, month: pd.Timestamp, interval: str | None = None, base_url: str = BASE_URL) -> str:
    ym = month.strftime("%Y-%m")
    symbol = symbol.upper()
    if kind == "aggTrades":
        rel = f"data/spot/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{ym}.zip"
    elif kind == "klines":
        if not interval:
            raise ValueError("kline interval required")
        rel = f"data/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
    else:
        raise ValueError(f"unsupported Binance archive kind: {kind}")
    return f"{base_url.rstrip('/')}/{rel}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, *, force: bool = False, client: httpx.Client | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    owns = client is None
    c = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120.0, connect=30.0))
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
        tmp.replace(dest)
        return dest
    finally:
        if owns:
            c.close()


def download_archive(kind: str, symbol: str, month: pd.Timestamp, cache_dir: str | Path, *, interval: str | None = None, force: bool = False, base_url: str = BASE_URL) -> Path:
    url = _archive_url(kind, symbol, month, interval=interval, base_url=base_url)
    dest = Path(cache_dir) / Path(url).name
    return _download(url, dest, force=force)


def _timestamp_unit(values: pd.Series) -> str:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return "us"
    return "us" if float(x.median()) >= 1e14 else "ms"


def _epoch_us(values) -> np.ndarray:
    """Convert datetime-like values to Unix microseconds independent of pandas resolution.

    pandas 3 can preserve ``datetime64[us]`` rather than coercing everything to
    nanoseconds.  Dividing ``astype("int64")`` by 1000 therefore becomes
    resolution-dependent.  Converting explicitly to ``datetime64[us]`` makes
    the archive matcher stable across pandas 2.x/3.x and operating systems.
    """
    ts = pd.to_datetime(values, utc=True)
    if isinstance(ts, pd.Series):
        arr = ts.to_numpy(dtype="datetime64[us]")
    else:
        arr = np.asarray(ts, dtype="datetime64[us]")
    return arr.astype(np.int64, copy=False)


def _timestamp_epoch_us(value) -> int:
    return int(_epoch_us([value])[0])


def _read_zip_chunks(path: Path, names: list[str], chunksize: int = 500_000):
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith((".csv", ".txt"))]
        if not members:
            raise ValueError(f"no CSV member in {path}")
        with zf.open(members[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            yield from pd.read_csv(text, header=None, names=names, chunksize=chunksize, low_memory=False)


def load_5m_reference(symbol: str, start, end, cache_dir: str | Path, *, force: bool = False, base_url: str = BASE_URL) -> pd.DataFrame:
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    if start.tzinfo is None: start = start.tz_localize("UTC")
    if end.tzinfo is None: end = end.tz_localize("UTC")
    rows = []
    for month in _month_starts(start, end):
        path = download_archive("klines", symbol, month, cache_dir, interval="5m", force=force, base_url=base_url)
        for chunk in _read_zip_chunks(path, KLINE_COLUMNS, chunksize=250_000):
            raw = pd.to_numeric(chunk["close_time_raw"], errors="coerce")
            valid = raw.notna()
            if not valid.any():
                continue
            unit = _timestamp_unit(raw[valid])
            ts = pd.to_datetime(raw[valid].astype("int64"), unit=unit, utc=True)
            price = pd.to_numeric(chunk.loc[valid, "close"], errors="coerce").to_numpy()
            part = pd.DataFrame({"timestamp": ts.to_numpy(), "mid": price})
            rows.append(part)
    if not rows:
        raise RuntimeError(f"no Binance 5m data loaded for {symbol}")
    out = pd.concat(rows, ignore_index=True).dropna().sort_values("timestamp")
    out = out[(out["timestamp"] >= start) & (out["timestamp"] <= end)].copy()
    out["source"] = "binance_5m_kline"
    out["alignment_eligible"] = False
    out["regime_eligible"] = True
    return out.reset_index(drop=True)


def load_last_trades_for_targets(symbol: str, target_timestamps, cache_dir: str | Path, *, max_age_seconds: float = 3.0, force: bool = False, base_url: str = BASE_URL) -> pd.DataFrame:
    """Extract only the last Binance aggregate trade at/before each target timestamp.

    Monthly aggregate-trade archives are scanned once and reduced to sparse rows;
    the full multi-month trade tape is never materialized in memory.
    """
    targets = pd.Series(pd.to_datetime(pd.Series(target_timestamps), utc=True).dropna().unique()).sort_values().reset_index(drop=True)
    if targets.empty:
        return pd.DataFrame(columns=["timestamp", "mid", "source", "alignment_eligible", "regime_eligible", "target_timestamp", "age_seconds"])
    target_us = _epoch_us(targets)
    result_time = np.full(len(targets), -1, dtype=np.int64)
    result_price = np.full(len(targets), np.nan, dtype=float)
    cursor = 0
    months = _month_starts(
        targets.iloc[0] - pd.Timedelta(seconds=float(max_age_seconds)),
        targets.iloc[-1],
    )
    carry_t = None; carry_p = None
    for month in months:
        path = download_archive("aggTrades", symbol, month, cache_dir, force=force, base_url=base_url)
        for chunk in _read_zip_chunks(path, AGG_COLUMNS):
            raw = pd.to_numeric(chunk["timestamp_raw"], errors="coerce")
            price = pd.to_numeric(chunk["price"], errors="coerce")
            valid = raw.notna() & price.notna()
            if not valid.any():
                continue
            vals = raw[valid].astype("int64").to_numpy()
            unit = _timestamp_unit(raw[valid])
            trade_us = vals if unit == "us" else vals * 1000
            trade_p = price[valid].astype(float).to_numpy()
            if carry_t is not None and trade_us[0] > carry_t:
                trade_us = np.concatenate([[carry_t], trade_us])
                trade_p = np.concatenate([[carry_p], trade_p])
            max_t = int(trade_us[-1])
            hi = int(np.searchsorted(target_us, max_t, side="right"))
            if hi > cursor:
                t_slice = target_us[cursor:hi]
                idx = np.searchsorted(trade_us, t_slice, side="right") - 1
                ok = idx >= 0
                dest = np.arange(cursor, hi)[ok]
                result_time[dest] = trade_us[idx[ok]]
                result_price[dest] = trade_p[idx[ok]]
                cursor = hi
            carry_t = int(trade_us[-1]); carry_p = float(trade_p[-1])
        # Any targets later in this calendar month but after the last archive
        # trade can still use the final trade, subject to the 3-second staleness rule.
        month_end = _timestamp_epoch_us(month + pd.offsets.MonthBegin(1)) - 1
        hi = int(np.searchsorted(target_us, month_end, side="right"))
        if carry_t is not None and hi > cursor:
            dest = np.arange(cursor, hi)
            result_time[dest] = carry_t
            result_price[dest] = carry_p
            cursor = hi
    age = (target_us - result_time) / 1_000_000.0
    ok = (result_time >= 0) & np.isfinite(result_price) & (age >= 0) & (age <= float(max_age_seconds))
    out = pd.DataFrame({
        "target_timestamp": targets[ok].to_numpy(),
        "timestamp": pd.to_datetime(result_time[ok], unit="us", utc=True),
        "mid": result_price[ok],
        "last_trade": result_price[ok],
        "age_seconds": age[ok],
        "source": "binance_spot_aggtrade",
        "alignment_eligible": True,
        "regime_eligible": False,
    })
    return out.sort_values(["target_timestamp", "timestamp"]).reset_index(drop=True)


def build_reference(symbol: str, start, end, target_timestamps, cache_dir: str | Path, *, max_age_seconds: float = 3.0, force: bool = False, base_url: str = BASE_URL) -> pd.DataFrame:
    regime = load_5m_reference(symbol, start, end, cache_dir, force=force, base_url=base_url)
    exact = load_last_trades_for_targets(symbol, target_timestamps, cache_dir, max_age_seconds=max_age_seconds, force=force, base_url=base_url)
    frames=[regime]
    if not exact.empty:
        frames.append(exact)
    out = pd.concat(frames, ignore_index=True, sort=False)
    return out.sort_values("timestamp").reset_index(drop=True)
