from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from houseedge.config import (
    calibration_basis_hash,
    canonical_hash,
    load_yaml,
    reference_policy_hash,
    with_reference_policy_selection,
)
from houseedge.data.base_rpc import window_timestamps
from houseedge.data.binance_public import load_5m_reference
from houseedge.data.binance_public import (
    load_last_trades_for_targets as load_binance_last_trades,
)
from houseedge.data.bybit_public import (
    load_last_trades_for_targets as load_bybit_last_trades,
)
from houseedge.data.storage import artifact_sha256, artifact_size, write_frame

POLICY_NAME = "binance_spot_then_bybit_spot"


def _event_parts(path: str | Path) -> list[Path]:
    event_path = Path(path)
    parts = sorted(event_path.glob("part-*.parquet")) if event_path.is_dir() else [event_path]
    if not parts or any(not part.exists() for part in parts):
        raise FileNotFoundError(f"No existing Base event parquet parts found under {event_path}")
    return parts


def load_swap_target_counts(path: str | Path) -> pd.DataFrame:
    """Read only event/timestamp columns and retain timestamp multiplicity."""
    grouped = []
    for part in _event_parts(path):
        frame = pd.read_parquet(part, columns=["event", "timestamp"])
        swaps = frame.loc[frame["event"].eq("Swap"), "timestamp"]
        if swaps.empty:
            continue
        timestamps = pd.to_datetime(swaps, utc=True).astype("datetime64[ns, UTC]")
        grouped.append(
            timestamps.value_counts()
            .rename_axis("target_timestamp")
            .rename("swap_count")
            .reset_index()
        )
    if not grouped:
        raise RuntimeError(f"Event dataset {path} contains no swaps")
    counts = pd.concat(grouped, ignore_index=True)
    return (
        counts.groupby("target_timestamp", as_index=False)["swap_count"]
        .sum()
        .sort_values("target_timestamp")
        .reset_index(drop=True)
    )


def _eligible_matches(frame: pd.DataFrame, tolerance_seconds: float) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["target_timestamp"] = pd.to_datetime(out["target_timestamp"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    out["age_seconds"] = (
        out["target_timestamp"] - out["timestamp"]
    ).dt.total_seconds()
    out = out[
        out["age_seconds"].ge(0)
        & out["age_seconds"].le(float(tolerance_seconds))
    ].copy()
    if (out["timestamp"] > out["target_timestamp"]).any():
        raise RuntimeError("Reference policy received a future observation")
    return (
        out.sort_values(["target_timestamp", "timestamp"])
        .drop_duplicates("target_timestamp", keep="last")
        .reset_index(drop=True)
    )


def compose_priority_fallback(
    target_counts: pd.DataFrame,
    primary: pd.DataFrame,
    fallback: pd.DataFrame,
    *,
    tolerance_seconds: float,
) -> tuple[pd.DataFrame, dict]:
    """Choose Binance when fresh, otherwise the fresh Bybit observation."""
    targets = target_counts[["target_timestamp", "swap_count"]].copy()
    targets["target_timestamp"] = pd.to_datetime(
        targets["target_timestamp"], utc=True
    ).astype("datetime64[ns, UTC]")
    primary = _eligible_matches(primary, tolerance_seconds)
    fallback = _eligible_matches(fallback, tolerance_seconds)

    def slim(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(
                columns=[
                    "target_timestamp",
                    f"{prefix}_timestamp",
                    f"{prefix}_mid",
                    f"{prefix}_age_seconds",
                    f"{prefix}_source",
                ]
            )
        return frame[
            ["target_timestamp", "timestamp", "mid", "age_seconds", "source"]
        ].rename(
            columns={
                "timestamp": f"{prefix}_timestamp",
                "mid": f"{prefix}_mid",
                "age_seconds": f"{prefix}_age_seconds",
                "source": f"{prefix}_source",
            }
        )

    merged = targets.merge(slim(primary, "primary"), on="target_timestamp", how="left")
    merged = merged.merge(slim(fallback, "fallback"), on="target_timestamp", how="left")
    use_primary = merged["primary_mid"].notna()
    use_fallback = ~use_primary & merged["fallback_mid"].notna()
    covered = use_primary | use_fallback

    selected = merged.loc[covered, ["target_timestamp", "swap_count"]].copy()
    selected["timestamp"] = merged.loc[covered, "primary_timestamp"].where(
        use_primary[covered], merged.loc[covered, "fallback_timestamp"]
    )
    selected["mid"] = merged.loc[covered, "primary_mid"].where(
        use_primary[covered], merged.loc[covered, "fallback_mid"]
    )
    selected["last_trade"] = selected["mid"]
    selected["age_seconds"] = merged.loc[covered, "primary_age_seconds"].where(
        use_primary[covered], merged.loc[covered, "fallback_age_seconds"]
    )
    selected["source"] = merged.loc[covered, "primary_source"].where(
        use_primary[covered], merged.loc[covered, "fallback_source"]
    )
    selected["reference_policy"] = POLICY_NAME
    selected["alignment_eligible"] = True
    selected["regime_eligible"] = False

    total_swaps = int(targets["swap_count"].sum())
    primary_swaps = int(merged.loc[use_primary, "swap_count"].sum())
    fallback_swaps = int(merged.loc[use_fallback, "swap_count"].sum())
    matched_swaps = primary_swaps + fallback_swaps
    metrics = {
        "swaps": total_swaps,
        "matched": matched_swaps,
        "missing": total_swaps - matched_swaps,
        "coverage": matched_swaps / max(total_swaps, 1),
        "missing_fraction": (total_swaps - matched_swaps) / max(total_swaps, 1),
        "primary_swaps": primary_swaps,
        "fallback_swaps": fallback_swaps,
    }
    return selected.sort_values("target_timestamp").reset_index(drop=True), metrics


def select_calibration_policy(
    target_counts: pd.DataFrame,
    primary: pd.DataFrame,
    fallback: pd.DataFrame,
    *,
    freshness_grid_seconds: list[float],
    required_coverage: float,
) -> tuple[float | None, list[dict]]:
    """Select the smallest predeclared freshness that passes calibration."""
    grid = []
    selected = None
    for tolerance in sorted({float(value) for value in freshness_grid_seconds}):
        _, metrics = compose_priority_fallback(
            target_counts,
            primary,
            fallback,
            tolerance_seconds=tolerance,
        )
        row = {"max_age_seconds": tolerance, **metrics}
        row["passes"] = bool(metrics["coverage"] >= required_coverage)
        grid.append(row)
        if selected is None and row["passes"]:
            selected = tolerance
    return selected, grid


def _calibration_overlap_diagnostic(
    primary: pd.DataFrame,
    fallback: pd.DataFrame,
    tolerance_seconds: float,
) -> dict:
    p = _eligible_matches(primary, tolerance_seconds)[["target_timestamp", "mid"]].rename(
        columns={"mid": "primary_mid"}
    )
    f = _eligible_matches(fallback, tolerance_seconds)[["target_timestamp", "mid"]].rename(
        columns={"mid": "fallback_mid"}
    )
    overlap = p.merge(f, on="target_timestamp", how="inner")
    if overlap.empty:
        return {"overlapping_targets": 0, "median_absolute_difference_bps": None, "p99_absolute_difference_bps": None}
    difference = np.abs(overlap["primary_mid"] / overlap["fallback_mid"] - 1.0) * 1e4
    return {
        "overlapping_targets": len(overlap),
        "median_absolute_difference_bps": float(np.median(difference)),
        "p99_absolute_difference_bps": float(np.quantile(difference, 0.99)),
    }


def _window(cfg: dict, key: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    window = cfg["calibration"][key]
    return window_timestamps(window["start"], window["end"])


def _write_config(path: Path, cfg: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _update_acquisition_manifest(root: Path, outputs: dict[str, str], cfg: dict) -> bool:
    """Refresh reference identities without touching immutable Base event entries."""
    path = root / "v015_acquisition_manifest.json"
    if not path.exists():
        return False
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.setdefault("outputs", {})
    for output in outputs.values():
        artifact = Path(output)
        try:
            key = str(artifact.relative_to(root)).replace("\\", "/")
        except ValueError:
            key = str(artifact)
        recorded[key] = {
            "bytes": artifact_size(artifact),
            "sha256": artifact_sha256(artifact),
            "kind": "dataset" if artifact.is_dir() else "file",
        }
    manifest["spec_sha256"] = canonical_hash(cfg)
    manifest["reference_policy_sha256"] = reference_policy_hash(cfg)
    manifest.setdefault("sources", {})["reference"] = {
        "policy": POLICY_NAME,
        "venues": ["binance_spot", "bybit_spot"],
        "backward_only": True,
        "selection_window": "calibration_only",
        "reference_policy_sha256": reference_policy_hash(cfg),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return True


def rebuild_multi_venue_references(
    *,
    config_path: str | Path = "configs/experiment_001.yaml",
    output_root: str | Path = "data",
    report_path: str | Path = "runs/v015_reference_feasibility.json",
    force_downloads: bool = False,
    apply_selection: bool = True,
    progress: Callable[[str], None] | None = None,
    binance_loader: Callable = load_binance_last_trades,
    bybit_loader: Callable = load_bybit_last_trades,
    regime_loader: Callable = load_5m_reference,
) -> dict:
    """Rebuild both references from existing events and report the fixed gate.

    Venue/freshness selection uses calibration coverage only. Candidate data is
    evaluated exactly once under that frozen selection and cannot alter it.
    This function never imports or calls Base/HyperSync acquisition.
    """
    emit = progress or (lambda _message: None)
    config_path = Path(config_path)
    cfg = load_yaml(config_path)
    allowed_missing = float(cfg["validity"]["max_missing_reference_fraction"])
    if abs(allowed_missing - 0.005) > 1e-12:
        raise RuntimeError("Experiment 001 reference feasibility requires the unchanged 0.5% missingness gate")
    required_coverage = 1.0 - allowed_missing

    policy = cfg["sample"]["reference_policy"]
    if policy.get("method") != "priority_fallback":
        raise ValueError(f"Unsupported reference policy method: {policy.get('method')}")
    venues = policy.get("venues", [])
    if [venue.get("id") for venue in venues] != ["binance_spot", "bybit_spot"]:
        raise ValueError("Reference venue order must be Binance spot then Bybit spot")
    if policy.get("selection_window") != "calibration_only":
        raise ValueError("Reference policy selection_window must be calibration_only")
    freshness_grid = [float(value) for value in policy["freshness_grid_seconds"]]
    if not freshness_grid or min(freshness_grid) <= 0:
        raise ValueError("Reference freshness grid must contain positive values")

    root = Path(output_root).expanduser().resolve()
    cache_root = root / "cache" / "reference"
    paths = {
        "calibration": root / "raw" / "calibration_events.parquet",
        "candidate": root / "raw" / "candidate_events.parquet",
    }
    emit("Reading calibration swap timestamps from existing Base event parts")
    calibration_counts = load_swap_target_counts(paths["calibration"])
    calibration_targets = calibration_counts["target_timestamp"]
    max_search_age = max(freshness_grid)

    binance_symbol = str(venues[0]["symbol"]).upper()
    bybit_symbol = str(venues[1]["symbol"]).upper()
    emit(f"Loading calibration {binance_symbol} Binance spot trades")
    calibration_primary = binance_loader(
        binance_symbol,
        calibration_targets,
        cache_root / "binance",
        max_age_seconds=max_search_age,
        force=force_downloads,
    )
    emit(f"Loading calibration {bybit_symbol} Bybit spot trades")
    calibration_fallback = bybit_loader(
        bybit_symbol,
        calibration_targets,
        cache_root / "bybit",
        max_age_seconds=max_search_age,
        force=force_downloads,
    )
    selected_age, grid = select_calibration_policy(
        calibration_counts,
        calibration_primary,
        calibration_fallback,
        freshness_grid_seconds=freshness_grid,
        required_coverage=required_coverage,
    )

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if selected_age is None:
        report = {
            "status": "FAIL_CALIBRATION_REFERENCE_COVERAGE",
            "required_coverage": required_coverage,
            "allowed_missing_fraction": allowed_missing,
            "policy": POLICY_NAME,
            "calibration_grid": grid,
            "selection_window": "calibration_only",
            "candidate_evaluated": False,
            "candidate_primary_lp_pnl_opened": False,
            "base_events_reused": True,
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    calibration_exact, calibration_metrics = compose_priority_fallback(
        calibration_counts,
        calibration_primary,
        calibration_fallback,
        tolerance_seconds=selected_age,
    )
    selected_cfg = with_reference_policy_selection(
        cfg,
        policy_name=POLICY_NAME,
        max_age_seconds=selected_age,
    )
    policy_sha256 = reference_policy_hash(selected_cfg)

    emit("Reading candidate swap timestamps for out-of-sample coverage only")
    candidate_counts = load_swap_target_counts(paths["candidate"])
    candidate_targets = candidate_counts["target_timestamp"]
    emit(f"Loading candidate {binance_symbol} Binance spot trades under the frozen policy")
    candidate_primary = binance_loader(
        binance_symbol,
        candidate_targets,
        cache_root / "binance",
        max_age_seconds=selected_age,
        force=force_downloads,
    )
    emit(f"Loading candidate {bybit_symbol} Bybit spot trades under the frozen policy")
    candidate_fallback = bybit_loader(
        bybit_symbol,
        candidate_targets,
        cache_root / "bybit",
        max_age_seconds=selected_age,
        force=force_downloads,
    )
    candidate_exact, candidate_metrics = compose_priority_fallback(
        candidate_counts,
        candidate_primary,
        candidate_fallback,
        tolerance_seconds=selected_age,
    )
    candidate_passes = candidate_metrics["coverage"] >= required_coverage

    references = {}
    for name, exact, window_key in (
        ("calibration", calibration_exact, "calibration_window"),
        ("candidate", candidate_exact, "candidate_primary_window"),
    ):
        start, end = _window(selected_cfg, window_key)
        emit(f"Loading Binance 5-minute {name} regime observations")
        regime = regime_loader(
            binance_symbol,
            start,
            end,
            cache_root / "binance",
            force=force_downloads,
        )
        reference = pd.concat([regime, exact], ignore_index=True, sort=False).sort_values(
            "timestamp"
        )
        output = root / name / "eth_reference.parquet"
        write_frame(reference, output)
        references[name] = str(output)

    manifest_will_update = bool(
        apply_selection and (root / "v015_acquisition_manifest.json").exists()
    )
    report = {
        "status": "PASS" if candidate_passes else "FAIL_CANDIDATE_REFERENCE_COVERAGE",
        "required_coverage": required_coverage,
        "allowed_missing_fraction": allowed_missing,
        "policy": POLICY_NAME,
        "method": "priority_fallback",
        "venue_order": ["binance_spot", "bybit_spot"],
        "selected_max_age_seconds": selected_age,
        "selection_rule": policy["selection_rule"],
        "selection_window": "calibration_only",
        "calibration_grid": grid,
        "calibration": calibration_metrics,
        "calibration_cross_venue_diagnostic": _calibration_overlap_diagnostic(
            calibration_primary,
            calibration_fallback,
            selected_age,
        ),
        "candidate_out_of_sample_coverage": {
            **candidate_metrics,
            "passes": bool(candidate_passes),
        },
        "candidate_used_for_policy_selection": False,
        "candidate_primary_lp_pnl_opened": False,
        "base_events_reused": True,
        "base_hypersync_download_invoked": False,
        "reference_policy_sha256": policy_sha256,
        "calibration_basis_sha256_after_selection": calibration_basis_hash(selected_cfg),
        "outputs": references,
        "acquisition_manifest_updated": manifest_will_update,
        "config_updated": bool(apply_selection),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if apply_selection:
        selected_cfg["sample"]["reference_policy"]["selection_report_sha256"] = _file_sha256(
            report_path
        )
        _write_config(config_path, selected_cfg)
        _update_acquisition_manifest(root, references, selected_cfg)
    return report
