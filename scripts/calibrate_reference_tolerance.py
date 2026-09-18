from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from houseedge.config import load_yaml
from houseedge.data.base_rpc import window_timestamps
from houseedge.data.binance_public import build_reference
from houseedge.data.reference import normalize_reference
from houseedge.data.storage import write_frame
from houseedge.research.alignment import align_reference


def _parts(path: Path) -> list[Path]:
    if path.is_dir():
        parts = sorted(path.glob("part-*.parquet"))
    else:
        parts = [path]
    if not parts:
        raise FileNotFoundError(f"No parquet event parts found under {path}")
    return parts


def _swap_targets(parts: list[Path]) -> pd.Series:
    chunks: list[pd.Series] = []
    for part in parts:
        frame = pd.read_parquet(part, columns=["event", "timestamp"])
        swaps = frame.loc[frame["event"].eq("Swap"), "timestamp"]
        if len(swaps):
            chunks.append(pd.to_datetime(swaps, utc=True))
    if not chunks:
        raise RuntimeError("Calibration event dataset contains no swaps")
    targets = pd.concat(chunks, ignore_index=True)
    return pd.Series(targets.dropna().unique()).sort_values().reset_index(drop=True)


def _direct_coverage(reference: pd.DataFrame, total_targets: int, tolerance: float) -> tuple[int, float]:
    exact = reference.copy()
    if "alignment_eligible" in exact:
        exact = exact[exact["alignment_eligible"].fillna(False).astype(bool)].copy()
    if "target_timestamp" not in exact or "age_seconds" not in exact:
        raise RuntimeError("Reference lacks target_timestamp/age_seconds needed for calibration")
    exact["target_timestamp"] = pd.to_datetime(exact["target_timestamp"], utc=True)
    ages = pd.to_numeric(exact["age_seconds"], errors="coerce")
    covered = exact.loc[ages.le(float(tolerance)), "target_timestamp"].nunique()
    return int(covered), float(covered / max(total_targets, 1))


def _filter_reference(reference: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    out = reference.copy()
    if "alignment_eligible" not in out:
        return out
    exact = out["alignment_eligible"].fillna(False).astype(bool)
    ages = pd.to_numeric(out.get("age_seconds"), errors="coerce")
    keep = (~exact) | (exact & ages.le(float(tolerance)))
    return out.loc[keep].reset_index(drop=True)


def _merge_coverage(parts: list[Path], reference: pd.DataFrame, tolerance: float) -> tuple[int, int, float]:
    ref = normalize_reference(reference)
    if "alignment_eligible" in ref:
        ref = ref[ref["alignment_eligible"].fillna(False).astype(bool)].copy()
    ref["timestamp"] = pd.to_datetime(ref["timestamp"], utc=True).astype("datetime64[ns, UTC]")

    total = 0
    matched = 0
    for part in parts:
        frame = pd.read_parquet(part, columns=["event", "timestamp"])
        swaps = frame[frame["event"].eq("Swap")].copy()
        if swaps.empty:
            continue
        swaps["timestamp"] = pd.to_datetime(swaps["timestamp"], utc=True).astype("datetime64[ns, UTC]")
        lo = swaps["timestamp"].min() - pd.Timedelta(seconds=float(tolerance))
        hi = swaps["timestamp"].max()
        rp = ref[(ref["timestamp"] >= lo) & (ref["timestamp"] <= hi)].copy()
        aligned = align_reference(swaps, rp, float(tolerance), 0)
        total += len(aligned)
        matched += int(aligned["ref_mid"].notna().sum())
    return total, matched, float(matched / max(total, 1))


def _update_config_tolerance(path: Path, tolerance: float) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = r"(?m)^(\s*max_age_seconds:\s*).*$"
    replacement = rf"\g<1>{float(tolerance):g}"
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError("Could not uniquely update sample.primary_alignment.max_age_seconds")
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Outcome-blind calibration of the minimum Binance reference freshness tolerance."
    )
    parser.add_argument("--config", default="configs/experiment_001.yaml")
    parser.add_argument("--events", default="data/raw/calibration_events.parquet")
    parser.add_argument("--output", default="data/calibration/eth_reference.parquet")
    parser.add_argument("--cache", default="data/cache/binance")
    parser.add_argument("--report", default="runs/v015_reference_calibration.json")
    parser.add_argument("--search-max-seconds", type=float, default=60.0)
    parser.add_argument("--tolerances", default="3,5,10,15,30,60")
    parser.add_argument("--force-downloads", action="store_true")
    parser.add_argument("--no-apply", action="store_true")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg = load_yaml(cfg_path)
    symbol = str(cfg.get("sample", {}).get("primary_reference_symbol", "ETHUSDT")).upper()
    allowed_missing = float(cfg["validity"]["max_missing_reference_fraction"])
    required_coverage = 1.0 - allowed_missing
    tolerances = sorted({float(x.strip()) for x in args.tolerances.split(",") if x.strip()})
    if not tolerances:
        raise ValueError("No tolerance grid supplied")
    if max(tolerances) > float(args.search_max_seconds):
        raise ValueError("search-max-seconds must be >= largest tolerance")

    event_path = Path(args.events)
    parts = _parts(event_path)
    print(f"Reading calibration swap timestamps from {event_path} ...", flush=True)
    targets = _swap_targets(parts)
    print(f"Found {len(targets):,} unique calibration swap timestamps.", flush=True)

    win = cfg["calibration"]["calibration_window"]
    start, end = window_timestamps(win["start"], win["end"])
    print(
        f"Building {symbol} calibration reference with up to {args.search_max_seconds:g}s lookback "
        "(no Base/HyperSync download) ...",
        flush=True,
    )
    raw_ref = build_reference(
        symbol,
        start,
        end,
        targets,
        args.cache,
        max_age_seconds=float(args.search_max_seconds),
        force=bool(args.force_downloads),
    )

    grid = []
    selected = None
    for tol in tolerances:
        covered, coverage = _direct_coverage(raw_ref, len(targets), tol)
        row = {
            "tolerance_seconds": tol,
            "covered_unique_targets": covered,
            "total_unique_targets": int(len(targets)),
            "coverage": coverage,
            "missing_pct": 100.0 * (1.0 - coverage),
            "passes": coverage >= required_coverage,
        }
        grid.append(row)
        print(
            f"  {tol:>5g}s: {100.0*coverage:8.4f}% coverage "
            f"({row['missing_pct']:.4f}% missing)"
            + ("  PASS" if row["passes"] else ""),
            flush=True,
        )
        if selected is None and row["passes"]:
            selected = tol

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if selected is None:
        report = {
            "status": "FAIL_REFERENCE_UNSUITABLE",
            "symbol": symbol,
            "required_coverage": required_coverage,
            "allowed_missing_fraction": allowed_missing,
            "search_max_seconds": float(args.search_max_seconds),
            "grid": grid,
            "outcome_blind": True,
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            f"\nREFERENCE CALIBRATION FAILED: {symbol} cannot reach the preregistered "
            f"{100*required_coverage:.2f}% coverage even at {max(tolerances):g}s.",
            flush=True,
        )
        print(f"Report: {report_path}")
        raise SystemExit(2)

    selected_ref = _filter_reference(raw_ref, selected)
    total_swaps, matched_swaps, merge_coverage = _merge_coverage(parts, selected_ref, selected)
    merge_pass = merge_coverage >= required_coverage

    status = "PASS" if merge_pass else "FAIL_ALIGNMENT_IMPLEMENTATION"
    report = {
        "status": status,
        "symbol": symbol,
        "selected_tolerance_seconds": selected,
        "selection_rule": "smallest calibration-only tolerance in the preregistered grid reaching required coverage",
        "required_coverage": required_coverage,
        "allowed_missing_fraction": allowed_missing,
        "grid": grid,
        "merge_verification": {
            "swaps": int(total_swaps),
            "matched": int(matched_swaps),
            "coverage": merge_coverage,
            "missing_pct": 100.0 * (1.0 - merge_coverage),
            "passes": merge_pass,
        },
        "outcome_blind": True,
        "primary_lp_pnl_opened": False,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not merge_pass:
        print(
            f"\nREFERENCE TARGET COVERAGE PASSED at {selected:g}s, but actual merge coverage was only "
            f"{100*merge_coverage:.4f}%. This is an alignment implementation bug, not a reason to loosen the gate.",
            flush=True,
        )
        print(f"Report: {report_path}")
        raise SystemExit(3)

    if not args.no_apply:
        write_frame(selected_ref, args.output)
        _update_config_tolerance(cfg_path, selected)

    print(
        f"\nREFERENCE CALIBRATION PASS — selected {selected:g}s; "
        f"merge coverage {100*merge_coverage:.4f}%.",
        flush=True,
    )
    if args.no_apply:
        print("No files changed because --no-apply was supplied.")
    else:
        print(f"Updated: {cfg_path}")
        print(f"Wrote:   {args.output}")
    print(f"Report:  {report_path}")


if __name__ == "__main__":
    main()
