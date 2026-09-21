from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import timedelta

import numpy as np
import pandas as pd

from houseedge.config import load_yaml
from houseedge.data.binance_public import (
    AGG_COLUMNS,
    BASE_URL,
    _download,
    _read_zip_chunks,
    _timestamp_unit,
)
from houseedge.data.reference import normalize_reference
from houseedge.data.storage import read_frame, write_frame
from houseedge.research.alignment import align_reference

TRADE_COLUMNS = [
    "trade_id",
    "price",
    "quantity",
    "quote_quantity",
    "timestamp_raw",
    "buyer_is_maker",
    "best_match",
]


def _ns_utc(values) -> pd.Series:
    return pd.Series(pd.to_datetime(values, utc=True)).astype("datetime64[ns, UTC]")


def _to_us(values) -> np.ndarray:
    ts = pd.to_datetime(values, utc=True)
    if isinstance(ts, pd.Series):
        arr = ts.to_numpy(dtype="datetime64[us]")
    else:
        arr = np.asarray(ts, dtype="datetime64[us]")
    return arr.astype(np.int64, copy=False)


def _event_parts(path: Path) -> list[Path]:
    parts = sorted(path.glob("part-*.parquet")) if path.is_dir() else [path]
    if not parts:
        raise FileNotFoundError(f"No parquet event parts found under {path}")
    return parts


def _unique_swap_targets(parts: list[Path]) -> pd.Series:
    chunks = []
    for part in parts:
        frame = pd.read_parquet(part, columns=["event", "timestamp"])
        s = frame.loc[frame["event"].eq("Swap"), "timestamp"]
        if len(s):
            chunks.append(_ns_utc(s))
    if not chunks:
        raise RuntimeError("Candidate event dataset contains no swaps")
    out = pd.concat(chunks, ignore_index=True).dropna()
    return pd.Series(out.unique()).sort_values().reset_index(drop=True)


def _daily_url(kind: str, symbol: str, day: pd.Timestamp) -> str:
    date = day.strftime("%Y-%m-%d")
    return (
        f"{BASE_URL}/data/spot/daily/{kind}/{symbol}/"
        f"{symbol}-{kind}-{date}.zip"
    )


def _daily_file(kind: str, symbol: str, day: pd.Timestamp, cache: Path) -> Path:
    url = _daily_url(kind, symbol, day)
    dest = cache / "daily" / kind / symbol / Path(url).name
    return _download(url, dest, force=False)


def _last_prices_from_zip(
    path: Path,
    targets: pd.Series,
    *,
    columns: list[str],
    timestamp_col: str,
    price_col: str,
    tolerance_seconds: float,
) -> pd.DataFrame:
    if targets.empty:
        return pd.DataFrame(columns=["target_timestamp", "timestamp", "mid", "age_seconds"])
    target_ts = _ns_utc(targets).sort_values().reset_index(drop=True)
    target_us = _to_us(target_ts)
    result_time = np.full(len(target_ts), -1, dtype=np.int64)
    result_price = np.full(len(target_ts), np.nan, dtype=float)
    cursor = 0
    carry_t = None
    carry_p = None

    for chunk in _read_zip_chunks(path, columns):
        raw = pd.to_numeric(chunk[timestamp_col], errors="coerce")
        price = pd.to_numeric(chunk[price_col], errors="coerce")
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
        carry_t = int(trade_us[-1])
        carry_p = float(trade_p[-1])

    if carry_t is not None and cursor < len(target_ts):
        dest = np.arange(cursor, len(target_ts))
        result_time[dest] = carry_t
        result_price[dest] = carry_p

    age = (target_us - result_time) / 1_000_000.0
    ok = (
        (result_time >= 0)
        & np.isfinite(result_price)
        & (age >= 0)
        & (age <= float(tolerance_seconds))
    )
    return pd.DataFrame(
        {
            "target_timestamp": target_ts[ok].to_numpy(),
            "timestamp": pd.to_datetime(result_time[ok], unit="us", utc=True),
            "mid": result_price[ok],
            "age_seconds": age[ok],
        }
    )


def _merge_coverage(
    parts: list[Path], reference: pd.DataFrame, tolerance: float
) -> tuple[int, int, float]:
    ref = normalize_reference(reference)
    if "alignment_eligible" in ref:
        ref = ref[ref["alignment_eligible"].fillna(False).astype(bool)].copy()
    ref["timestamp"] = _ns_utc(ref["timestamp"]).to_numpy()
    total = 0
    matched = 0
    for part in parts:
        frame = pd.read_parquet(part, columns=["event", "timestamp"])
        swaps = frame[frame["event"].eq("Swap")].copy()
        if swaps.empty:
            continue
        swaps["timestamp"] = _ns_utc(swaps["timestamp"]).to_numpy()
        lo = swaps["timestamp"].min() - pd.Timedelta(seconds=float(tolerance))
        hi = swaps["timestamp"].max()
        rp = ref[(ref["timestamp"] >= lo) & (ref["timestamp"] <= hi)].copy()
        aligned = align_reference(swaps, rp, float(tolerance), 0)
        total += len(aligned)
        matched += int(aligned["ref_mid"].notna().sum())
    return total, matched, matched / max(total, 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Repair candidate Binance reference gaps with official daily archives "
            "without changing the frozen freshness/coverage rule."
        )
    )
    parser.add_argument("--config", default="configs/experiment_001.yaml")
    parser.add_argument("--events", default="data/raw/candidate_events.parquet")
    parser.add_argument("--reference", default="data/candidate/eth_reference.parquet")
    parser.add_argument("--cache", default="data/cache/binance")
    parser.add_argument("--report", default="runs/v015_candidate_reference_repair.json")
    args = parser.parse_args()

    cfg = load_yaml(args.config)
    symbol = str(cfg.get("sample", {}).get("primary_reference_symbol", "ETHUSDT")).upper()
    tolerance = float(cfg["sample"]["primary_alignment"]["max_age_seconds"])
    allowed_missing = float(cfg["validity"]["max_missing_reference_fraction"])
    required = 1.0 - allowed_missing

    parts = _event_parts(Path(args.events))
    targets = _unique_swap_targets(parts)
    current = read_frame(args.reference)
    exact = current.copy()
    if "alignment_eligible" in exact:
        exact = exact[exact["alignment_eligible"].fillna(False).astype(bool)].copy()

    # Identify the timestamps that actually fail the same merge used by the
    # experiment, rather than trusting target_timestamp metadata alone.
    ref_for_merge = normalize_reference(current)
    if "alignment_eligible" in ref_for_merge:
        ref_for_merge = ref_for_merge[
            ref_for_merge["alignment_eligible"].fillna(False).astype(bool)
        ].copy()
    ref_for_merge["timestamp"] = _ns_utc(ref_for_merge["timestamp"]).to_numpy()
    missing_chunks = []
    for part in parts:
        frame = pd.read_parquet(part, columns=["event", "timestamp"])
        swaps = frame[frame["event"].eq("Swap")].copy()
        if swaps.empty:
            continue
        swaps["timestamp"] = _ns_utc(swaps["timestamp"]).to_numpy()
        lo = swaps["timestamp"].min() - pd.Timedelta(seconds=tolerance)
        hi = swaps["timestamp"].max()
        rp = ref_for_merge[(ref_for_merge["timestamp"] >= lo) & (ref_for_merge["timestamp"] <= hi)].copy()
        aligned = align_reference(swaps, rp, tolerance, 0)
        bad = aligned.loc[aligned["ref_mid"].isna(), "timestamp"]
        if len(bad):
            missing_chunks.append(_ns_utc(bad))
    if missing_chunks:
        missing = pd.concat(missing_chunks, ignore_index=True).dropna().drop_duplicates().sort_values().reset_index(drop=True)
    else:
        missing = pd.Series([], dtype="datetime64[ns, UTC]")

    print(
        f"{symbol}: {len(missing):,} of {len(targets):,} unique candidate swap timestamps "
        f"need archive repair; frozen tolerance={tolerance:g}s.",
        flush=True,
    )

    repaired_rows = []
    remaining = missing.copy()
    cache = Path(args.cache)

    for kind, columns, ts_col in (
        ("aggTrades", AGG_COLUMNS, "timestamp_raw"),
        ("trades", TRADE_COLUMNS, "timestamp_raw"),
    ):
        if remaining.empty:
            break
        found_parts = []
        days = pd.Series(remaining.dt.floor("D").unique()).sort_values()
        print(f"Trying official daily {kind} on {len(days)} affected UTC days ...", flush=True)
        for i, day_value in enumerate(days, 1):
            day = pd.Timestamp(day_value)
            day_targets = remaining[remaining.dt.floor("D").eq(day)].reset_index(drop=True)
            try:
                archive = _daily_file(kind, symbol, day, cache)
            except Exception as exc:
                print(f"  {day.date()}: daily {kind} unavailable ({type(exc).__name__})", flush=True)
                continue
            found = _last_prices_from_zip(
                archive,
                day_targets,
                columns=columns,
                timestamp_col=ts_col,
                price_col="price",
                tolerance_seconds=tolerance,
            )
            if not found.empty:
                found["last_trade"] = found["mid"]
                found["source"] = f"binance_spot_{kind}_daily_repair"
                found["alignment_eligible"] = True
                found["regime_eligible"] = False
                found_parts.append(found)
            if i % 25 == 0 or i == len(days):
                print(f"  {kind}: {i}/{len(days)} days checked", flush=True)
        if found_parts:
            found = pd.concat(found_parts, ignore_index=True, sort=False)
            repaired_rows.append(found)
            found_us = set(_to_us(found["target_timestamp"]).tolist())
            remain_us = _to_us(remaining)
            remaining = remaining[
                np.array([int(x) not in found_us for x in remain_us], dtype=bool)
            ].reset_index(drop=True)
            print(f"  {kind} repaired {len(found):,}; {len(remaining):,} targets remain.", flush=True)

    if repaired_rows:
        repair = pd.concat(repaired_rows, ignore_index=True, sort=False)
        # If both daily sources found a target, prefer aggTrades (first source tried).
        repair = repair.drop_duplicates("target_timestamp", keep="first")
        regime = current[
            ~current.get("alignment_eligible", pd.Series(False, index=current.index)).fillna(False).astype(bool)
        ].copy()
        old_exact = exact.copy()
        combined_exact = pd.concat([old_exact, repair], ignore_index=True, sort=False)
        combined_exact["target_timestamp"] = pd.to_datetime(combined_exact["target_timestamp"], utc=True)
        combined_exact = combined_exact.sort_values(["target_timestamp", "timestamp"]).drop_duplicates(
            "target_timestamp", keep="last"
        )
        candidate = pd.concat([regime, combined_exact], ignore_index=True, sort=False).sort_values("timestamp")
    else:
        candidate = current

    total, matched, coverage = _merge_coverage(parts, candidate, tolerance)
    status = "PASS_ARCHIVE_REPAIR" if coverage >= required else "FAIL_SINGLE_VENUE_COVERAGE"
    report = {
        "status": status,
        "symbol": symbol,
        "tolerance_seconds": tolerance,
        "required_coverage": required,
        "unique_targets_before_repair_missing": int(len(missing)),
        "unique_targets_after_repair_missing": int(len(remaining)),
        "merge": {
            "swaps": int(total),
            "matched": int(matched),
            "coverage": float(coverage),
            "missing_pct": float(100.0 * (1.0 - coverage)),
            "passes": bool(coverage >= required),
        },
        "candidate_lp_pnl_opened": False,
        "reference_rule_changed": False,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if coverage < required:
        print(
            f"\nFAIL_SINGLE_VENUE_COVERAGE — daily archive repair still leaves "
            f"{100.0*(1.0-coverage):.4f}% missing (> {100.0*allowed_missing:.4f}% allowed).",
            flush=True,
        )
        print("Original candidate reference was NOT replaced.", flush=True)
        print(f"Report: {report_path}", flush=True)
        raise SystemExit(2)

    reference_path = Path(args.reference)
    backup = reference_path.with_suffix(reference_path.suffix + ".pre-daily-repair")
    if not backup.exists():
        backup.write_bytes(reference_path.read_bytes())
    write_frame(candidate, reference_path)
    print(
        f"\nPASS_ARCHIVE_REPAIR — candidate merge coverage {100.0*coverage:.4f}%.",
        flush=True,
    )
    print(f"Updated: {reference_path}", flush=True)
    print(f"Backup:  {backup}", flush=True)
    print(f"Report:  {report_path}", flush=True)


if __name__ == "__main__":
    main()
