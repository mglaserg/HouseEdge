from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from houseedge.config import PoolSpec, canonical_hash
from houseedge.data.aave_base import fetch_usdc_supply_rates
from houseedge.data.base_rpc import block_at_or_after, block_at_or_before, window_timestamps, validate_historical_log_plan
from houseedge.data.binance_public import build_reference
from houseedge.data.hyperliquid import fetch_funding_history
from houseedge.data.reference import normalize_reference
from houseedge.data.storage import (
    write_frame, mark_dataset_complete, dataset_complete,
    artifact_size, artifact_sha256, read_frame, read_dataset_columns,
)
from houseedge.research.alignment import align_reference
from houseedge.research.protocol_fee import attach_protocol_fee_state
from houseedge.research.replay import (
    replay_discrete_hedged_lp, replay_discrete_hedged_lp_chunk,
    finalize_streaming_replay, StreamingReplayState,
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()



def _artifact_meta(path: Path) -> dict:
    size = artifact_size(path)
    if size <= 0:
        raise RuntimeError(f"Expected non-empty acquisition artifact: {path}")
    return {"sha256": artifact_sha256(path), "bytes": size, "kind": "dataset" if path.is_dir() else "file"}


def _fetch_hypersync_event_dataset(
    *,
    w3,
    pool: str,
    spec,
    b0: int,
    b1: int,
    settings,
    dataset_dir: Path,
    chunk_blocks: int,
    emit,
    force: bool = False,
) -> Path:
    """Fetch Uniswap events in bounded-memory block chunks to a resumable parquet dataset."""
    from houseedge.data.hypersync_base import fetch_uniswap_v3_events
    from houseedge.data.uniswap_base import read_fee_protocol_at_block

    dataset_dir = Path(dataset_dir)
    if force and dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    if dataset_complete(dataset_dir) and not force:
        emit(f"Using completed event dataset {dataset_dir}")
        return dataset_dir

    chunk_blocks = max(1, int(chunk_blocks))
    total_blocks = int(b1) - int(b0) + 1
    completed = 0
    total_rows = 0
    starts = list(range(int(b0), int(b1) + 1, chunk_blocks))
    for i, start in enumerate(starts, 1):
        end = min(start + chunk_blocks - 1, int(b1))
        stem = f"part-{start:012d}-{end:012d}"
        part = dataset_dir / f"{stem}.parquet"
        done = dataset_dir / f"{stem}.done.json"
        if done.exists() and not force:
            meta = json.loads(done.read_text(encoding="utf-8"))
            rows = int(meta.get("events", 0))
            if rows > 0 and (not part.exists() or part.stat().st_size <= 0):
                raise RuntimeError(f"Checkpoint says {rows} events but parquet part is missing: {part}")
            completed += end - start + 1
            total_rows += max(rows, 0)
            emit(f"Resuming: kept {stem} ({i}/{len(starts)}, {rows:,} events)")
            continue
        emit(f"HyperSync events {i}/{len(starts)}: blocks {start:,}..{end:,}")
        ev = fetch_uniswap_v3_events(pool, spec, start, end, settings=settings)
        initial_fee = read_fee_protocol_at_block(w3, pool, max(0, start - 1))
        ev = attach_protocol_fee_state(ev, initial_fee)
        rows = len(ev)
        if rows > 0:
            write_frame(ev, part)
        tmp_done = done.with_suffix(done.suffix + ".tmp")
        tmp_done.write_text(json.dumps({
            "from_block": start, "to_block": end, "events": rows,
            "parquet": part.name if rows > 0 else None,
        }, indent=2), encoding="utf-8")
        tmp_done.replace(done)
        total_rows += rows
        completed += end - start + 1
        pct = 100.0 * completed / max(total_blocks, 1)
        emit(f"Checkpointed {stem} ({rows:,} events) — {pct:.1f}% of block window")

    success = {
        "from_block": int(b0), "to_block": int(b1), "chunk_blocks": chunk_blocks,
        "parts": len(starts), "events": int(total_rows), "complete": True,
    }
    mark_dataset_complete(dataset_dir, success)
    emit(f"Completed event dataset {dataset_dir} ({len(starts)} parts)")
    return dataset_dir

def _window(cfg: dict, key: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    w = cfg["calibration"][key]
    return window_timestamps(w["start"], w["end"])


def _benchmark_incremental_returns(timestamps: pd.Series, rates: pd.DataFrame) -> np.ndarray:
    """Approximate event-to-event cash return using the rate active at interval start.

    Aave rate changes are sparse relative to swaps; this is used only to calibrate
    the noise/dependence process for prospective power, and the mean is removed
    by the power simulator.
    """
    t = pd.to_datetime(timestamps, utc=True).reset_index(drop=True)
    if len(t) == 0:
        return np.array([], dtype=float)
    r = rates[["timestamp","apy"]].copy()
    r["timestamp"] = pd.to_datetime(r["timestamp"], utc=True)
    r = r.sort_values("timestamp")
    starts = pd.DataFrame({"timestamp": t.shift(1).fillna(t.iloc[0])})
    active = pd.merge_asof(starts.sort_values("timestamp"), r, on="timestamp", direction="backward")
    if active["apy"].isna().any():
        raise ValueError("Aave calibration benchmark is missing a rate at/before replay start")
    dt_years = t.diff().dt.total_seconds().fillna(0.0).to_numpy() / (365.0 * 24 * 3600)
    apy = pd.to_numeric(active["apy"]).to_numpy(dtype=float)
    return np.expm1(np.log1p(apy) * dt_years)


def derive_calibration_excess_increments(
    calibration_events: pd.DataFrame,
    calibration_reference: pd.DataFrame,
    calibration_funding: pd.DataFrame,
    calibration_benchmark_rates: pd.DataFrame,
    cfg: dict,
) -> pd.DataFrame:
    """Replay only the sealed-away calibration window to estimate power noise.

    This function must never receive candidate-primary events. It returns only
    event-level excess-return increments; no calibration profitability decision
    is made or printed.
    """
    swaps = calibration_events[calibration_events["event"].eq("Swap")].copy()
    ref = normalize_reference(calibration_reference)
    align_cfg = cfg["sample"]["primary_alignment"]
    aligned = align_reference(swaps, ref, float(align_cfg["max_age_seconds"]), 0)
    matched = aligned["ref_mid"].notna()
    if float(matched.mean()) < 1.0 - float(cfg["validity"]["max_missing_reference_fraction"]):
        raise RuntimeError("Calibration reference alignment failed the preregistered missing-reference tolerance")
    aligned = aligned[matched].copy()
    spec = PoolSpec.from_config(cfg)
    p = cfg["position"]; h = cfg["hedge"]
    path, summary = replay_discrete_hedged_lp(
        aligned,
        capital_usd=float(p["initial_capital_usd"]),
        lower_multiplier=float(p["lower_multiplier"]),
        upper_multiplier=float(p["upper_multiplier"]),
        swap_fee_rate=float(spec.fee_tier_pips) / 1_000_000.0,
        lp_fee_fraction=1.0,
        delta_band_fraction_nav=float(h["trigger_residual_delta_fraction_lp_nav"]),
        hedge_to_zero=str(h["rebalance_target"]).lower() == "zero",
        hedge_taker_cost_bps=float(h["taker_cost_bps"]),
        funding_events=calibration_funding,
        annualized_funding_rate=None,
        # Fixed overhead changes the level, not the stochastic dependence used
        # for power. It remains in Gate 0 and the future primary economic P&L.
        fixed_operating_cost_usd=0.0,
        charge_initial_and_final_hedge_costs=bool(h.get("charge_initial_and_final_hedge_costs", True)),
        boundary_cross_fee_policy=str(p["boundary_cross_fee_policy"]),
        token0_decimals=spec.token0_decimals,
        token1_decimals=spec.token1_decimals,
    )
    cash = _benchmark_incremental_returns(path["timestamp"], calibration_benchmark_rates)
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(path["timestamp"], utc=True),
        "excess_return_inc": pd.to_numeric(path["net_pnl_inc_usd"]).to_numpy(dtype=float) / float(summary.initial_capital_usd) - cash,
    })
    out["timestamp"] = out["timestamp"].dt.floor("D")
    return out.groupby("timestamp",as_index=False)["excess_return_inc"].sum()



def _benchmark_incremental_returns_streaming(
    timestamps: pd.Series,
    rates: pd.DataFrame,
    previous_timestamp: pd.Timestamp | None,
) -> np.ndarray:
    """Event-to-event cash returns that remain continuous across dataset parts."""
    t = pd.Series(pd.to_datetime(timestamps, utc=True)).reset_index(drop=True)
    if len(t) == 0:
        return np.array([], dtype=float)
    r = rates[["timestamp", "apy"]].copy()
    r["timestamp"] = pd.to_datetime(r["timestamp"], utc=True)
    r = r.sort_values("timestamp")
    starts = t.shift(1)
    starts.iloc[0] = previous_timestamp if previous_timestamp is not None else t.iloc[0]
    q = pd.DataFrame({"timestamp": pd.to_datetime(starts, utc=True)})
    active = pd.merge_asof(q.sort_values("timestamp"), r, on="timestamp", direction="backward")
    if active["apy"].isna().any():
        raise ValueError("Aave calibration benchmark is missing a rate at/before replay interval")
    dt_years = (t - pd.to_datetime(starts, utc=True)).dt.total_seconds().to_numpy() / (365.0 * 24 * 3600)
    apy = pd.to_numeric(active["apy"]).to_numpy(dtype=float)
    return np.expm1(np.log1p(apy) * dt_years)


def derive_calibration_excess_increments_from_dataset(
    calibration_event_dataset: str | Path,
    calibration_reference: pd.DataFrame,
    calibration_funding: pd.DataFrame,
    calibration_benchmark_rates: pd.DataFrame,
    cfg: dict,
    *,
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Bounded-memory calibration replay from partitioned event history.

    The LP/hedge state is carried across parquet parts exactly once.  Output is
    aggregated to UTC daily excess-return increments, which is the dependence
    process used by prospective power and later primary bootstrap inference.
    Candidate-primary events are never accepted by this function.
    """
    emit = progress or (lambda _msg: None)
    path = Path(calibration_event_dataset)
    if path.is_dir():
        parts = sorted(path.glob("part-*.parquet"))
    else:
        parts = [path]
    if not parts:
        raise FileNotFoundError(f"No calibration parquet parts found under {path}")

    ref = normalize_reference(calibration_reference)
    align_cfg = cfg["sample"]["primary_alignment"]
    tolerance = float(align_cfg["max_age_seconds"])
    spec = PoolSpec.from_config(cfg)
    p = cfg["position"]; h = cfg["hedge"]
    state = StreamingReplayState()
    daily: dict[pd.Timestamp, float] = {}
    total_swaps = 0
    matched_swaps = 0
    previous_event_ts: pd.Timestamp | None = None

    for i, part in enumerate(parts, 1):
        ev = pd.read_parquet(part)
        if "timestamp" in ev:
            ev["timestamp"] = pd.to_datetime(ev["timestamp"], utc=True)
        swaps = ev[ev["event"].eq("Swap")].copy()
        del ev
        if swaps.empty:
            emit(f"Calibration replay {i}/{len(parts)}: {part.name} (no swaps)")
            continue
        total_swaps += len(swaps)
        lo = pd.Timestamp(swaps["timestamp"].min()) - pd.Timedelta(seconds=tolerance)
        hi = pd.Timestamp(swaps["timestamp"].max())
        ref_part = ref[(ref["timestamp"] >= lo) & (ref["timestamp"] <= hi)].copy()
        aligned = align_reference(swaps, ref_part, tolerance, 0)
        matched = aligned["ref_mid"].notna()
        matched_swaps += int(matched.sum())
        aligned = aligned[matched].copy()
        if aligned.empty:
            emit(f"Calibration replay {i}/{len(parts)}: {part.name} (0 aligned swaps)")
            continue
        path_inc, state = replay_discrete_hedged_lp_chunk(
            aligned, state=state,
            capital_usd=float(p["initial_capital_usd"]),
            lower_multiplier=float(p["lower_multiplier"]),
            upper_multiplier=float(p["upper_multiplier"]),
            swap_fee_rate=float(spec.fee_tier_pips) / 1_000_000.0,
            lp_fee_fraction=1.0,
            delta_band_fraction_nav=float(h["trigger_residual_delta_fraction_lp_nav"]),
            hedge_to_zero=str(h["rebalance_target"]).lower() == "zero",
            hedge_taker_cost_bps=float(h["taker_cost_bps"]),
            funding_events=calibration_funding,
            annualized_funding_rate=None,
            charge_initial_and_final_hedge_costs=bool(h.get("charge_initial_and_final_hedge_costs", True)),
            boundary_cross_fee_policy=str(p["boundary_cross_fee_policy"]),
            token0_decimals=spec.token0_decimals,
            token1_decimals=spec.token1_decimals,
        )
        cash = _benchmark_incremental_returns_streaming(path_inc["timestamp"], calibration_benchmark_rates, previous_event_ts)
        excess = pd.to_numeric(path_inc["net_pnl_inc_usd"]).to_numpy(dtype=float) / float(state.initial_value) - cash
        days = pd.to_datetime(path_inc["timestamp"], utc=True).dt.floor("D")
        for day, value in zip(days, excess):
            daily[day] = daily.get(day, 0.0) + float(value)
        previous_event_ts = pd.Timestamp(path_inc["timestamp"].iloc[-1])
        emit(f"Calibration replay {i}/{len(parts)}: {part.name} — {len(aligned):,} aligned swaps")

    if total_swaps == 0 or not state.initialized:
        raise RuntimeError("Calibration dataset contains no usable swaps")
    match_rate = matched_swaps / float(total_swaps)
    if match_rate < 1.0 - float(cfg["validity"]["max_missing_reference_fraction"]):
        raise RuntimeError(
            f"Calibration reference alignment failed tolerance: match_rate={match_rate:.6f}"
        )
    final_ts, final_adjustment = finalize_streaming_replay(
        state,
        hedge_taker_cost_bps=float(h["taker_cost_bps"]),
        charge_initial_and_final_hedge_costs=bool(h.get("charge_initial_and_final_hedge_costs", True)),
        fixed_operating_cost_usd=0.0,
    )
    final_day = pd.Timestamp(final_ts).floor("D")
    daily[final_day] = daily.get(final_day, 0.0) + final_adjustment / float(state.initial_value)
    out = pd.DataFrame({
        "timestamp": sorted(daily),
        "excess_return_inc": [daily[d] for d in sorted(daily)],
    })
    if len(out) < 10:
        raise RuntimeError("Streaming calibration replay produced fewer than 10 daily increments")
    return out

def acquire_v015_inputs(
    cfg: dict,
    *,
    output_root: str | Path = "data",
    rpc_url: str | None = None,
    chunk_blocks: int = 10_000,
    workers: int = 12,
    force_downloads: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Build every outcome-blind input required by `calibrate-design`.

    Candidate-primary LP P&L is intentionally never replayed here.
    """
    emit = progress or (lambda _msg: None)
    root = Path(output_root).expanduser().resolve()
    cal_dir = root / "calibration"
    cand_dir = root / "candidate"
    raw_dir = root / "raw"
    cache_dir = root / "cache" / "binance"
    for d in (cal_dir, cand_dir, raw_dir, cache_dir):
        d.mkdir(parents=True, exist_ok=True)

    from houseedge.data.uniswap_base import connect, fetch_events, read_fee_protocol_at_block
    w3 = connect(rpc_url)
    spec = PoolSpec.from_config(cfg)
    pool = spec.pool_address
    if not pool:
        raise RuntimeError("Experiment 001 requires a frozen pool address before acquisition")

    historical_cfg = cfg.get("historical_data", {})
    historical_source = str(historical_cfg.get("event_source", "RPC")).upper()
    if historical_source not in {"RPC", "HYPERSYNC"}:
        raise ValueError(f"Unsupported historical_data.event_source={historical_source!r}; expected RPC or HYPERSYNC")

    hypersync_settings = None
    hypersync_status = None
    if historical_source == "HYPERSYNC":
        from houseedge.data.hypersync_base import preflight as hypersync_preflight, settings_from_config
        hypersync_settings = settings_from_config(cfg)
        emit(f"Checking Envio HyperSync Base endpoint: {hypersync_settings.url}")
        hypersync_status = hypersync_preflight(hypersync_settings)

    cal_start, cal_end = _window(cfg, "calibration_window")
    cand_start, cand_end = _window(cfg, "candidate_primary_window")

    emit("Resolving Base block ranges from preregistered UTC windows")
    ranges = {
        "calibration": (block_at_or_after(w3, cal_start), block_at_or_before(w3, cal_end)),
        "candidate": (block_at_or_after(w3, cand_start), block_at_or_before(w3, cand_end)),
    }

    effective_chunk_blocks = None
    if historical_source == "RPC":
        total_blocks = sum((b1 - b0 + 1) for b0, b1 in ranges.values())
        effective_chunk_blocks = validate_historical_log_plan(
            w3, pool, requested_chunk_blocks=int(chunk_blocks), total_blocks=int(total_blocks)
        )
        if effective_chunk_blocks != int(chunk_blocks):
            emit(f"RPC log-range probe reduced chunk size: {int(chunk_blocks):,} -> {effective_chunk_blocks:,} blocks")

    event_frames = {}
    event_paths = {}
    for name, (b0, b1) in ranges.items():
        path = raw_dir / f"{name}_events.parquet"
        if historical_source == "HYPERSYNC":
            hs_chunk_blocks = int(historical_cfg.get("hypersync", {}).get("chunk_blocks", 100_000))
            emit(f"Fetching Base Uniswap v3 {name} events via bounded-memory HyperSync dataset: {b0:,}..{b1:,}")
            _fetch_hypersync_event_dataset(
                w3=w3, pool=pool, spec=spec, b0=b0, b1=b1, settings=hypersync_settings,
                dataset_dir=path, chunk_blocks=hs_chunk_blocks, emit=emit, force=force_downloads,
            )
            # Do not load the full multi-month dataset back into RAM here. Later
            # stages project only the columns they need; the calibration replay loads
            # the calibration window only when required.
            ev = None
        else:
            emit(f"Fetching Base Uniswap v3 {name} events via RPC: {b0:,}..{b1:,}")
            ev = fetch_events(w3, pool, spec, b0, b1, chunk_blocks=int(effective_chunk_blocks), workers=workers)
            initial_fee = read_fee_protocol_at_block(w3, pool, max(0, b0 - 1))
            ev = attach_protocol_fee_state(ev, initial_fee)
            write_frame(ev, path)
        event_paths[name] = path
        if ev is not None:
            event_frames[name] = ev
        if artifact_size(path) <= 0:
            raise RuntimeError(f"Failed to materialize event artifact: {path}")
        emit(f"Materialized {path} ({artifact_size(path):,} bytes)")

    symbol = "ETHUSDC"
    max_age = float(cfg["sample"]["primary_alignment"]["max_age_seconds"])
    references = {}
    for name, (start, end) in {"calibration": (cal_start, cal_end), "candidate": (cand_start, cand_end)}.items():
        emit(f"Downloading/scanning Binance {symbol} public archives for {name} reference")
        if name in event_frames:
            target_frame = event_frames[name][["event", "timestamp"]]
        else:
            target_frame = read_dataset_columns(event_paths[name], ["event", "timestamp"])
        targets = target_frame.loc[target_frame["event"].eq("Swap"), "timestamp"]
        del target_frame
        ref = build_reference(symbol, start, end, targets, cache_dir, max_age_seconds=max_age, force=force_downloads)
        references[name] = ref
        ref_path=(cal_dir if name == "calibration" else cand_dir) / "eth_reference.parquet"
        write_frame(ref, ref_path)
        if not ref_path.exists() or ref_path.stat().st_size == 0:
            raise RuntimeError(f"Failed to materialize reference artifact: {ref_path}")
        emit(f"Wrote {ref_path} ({ref_path.stat().st_size:,} bytes)")

    benchmarks = {}
    for name, (b0, b1) in ranges.items():
        if historical_source == "HYPERSYNC":
            from houseedge.data.aave_base import fetch_usdc_supply_rates_hypersync
            emit(f"Reconstructing Aave v3 Base USDC {name} supply APY via HyperSync + one RPC seed read")
            rates = fetch_usdc_supply_rates_hypersync(
                w3, b0, b1, settings=hypersync_settings, asset=cfg["pool"]["token1_address"],
                chunk_blocks=int(historical_cfg.get("hypersync", {}).get("chunk_blocks", 100_000)),
                emit=emit,
            )
        else:
            emit(f"Reconstructing Aave v3 Base USDC {name} supply APY via RPC")
            rates = fetch_usdc_supply_rates(
                w3, b0, b1, asset=cfg["pool"]["token1_address"],
                chunk_blocks=int(effective_chunk_blocks), workers=workers
            )
        benchmarks[name] = rates
        rate_path=(cal_dir if name == "calibration" else cand_dir) / "aave_base_usdc_apy.parquet"
        write_frame(rates, rate_path)
        if not rate_path.exists() or rate_path.stat().st_size == 0:
            raise RuntimeError(f"Failed to materialize benchmark artifact: {rate_path}")
        emit(f"Wrote {rate_path} ({rate_path.stat().st_size:,} bytes)")

    funding = {}
    for name, (start, end) in {"calibration": (cal_start, cal_end), "candidate": (cand_start, cand_end)}.items():
        emit(f"Fetching Hyperliquid ETH funding history for {name} window")
        f = fetch_funding_history("ETH", start, end)
        funding[name] = f
        funding_path=(cal_dir if name == "calibration" else cand_dir) / "hyperliquid_eth_funding.parquet"
        write_frame(f, funding_path)
        if not funding_path.exists() or funding_path.stat().st_size == 0:
            raise RuntimeError(f"Failed to materialize funding artifact: {funding_path}")
        emit(f"Wrote {funding_path} ({funding_path.stat().st_size:,} bytes)")

    emit("Deriving calibration-only daily excess-return increments with bounded memory")
    if historical_source == "HYPERSYNC":
        increments = derive_calibration_excess_increments_from_dataset(
            event_paths["calibration"], references["calibration"], funding["calibration"], benchmarks["calibration"], cfg, progress=emit
        )
    else:
        calibration_events = event_frames.get("calibration")
        if calibration_events is None:
            calibration_events = read_frame(event_paths["calibration"])
        increments = derive_calibration_excess_increments(
            calibration_events, references["calibration"], funding["calibration"], benchmarks["calibration"], cfg
        )
        del calibration_events
    increments_path=cal_dir / "excess_increments.parquet"
    write_frame(increments, increments_path)
    if not increments_path.exists() or increments_path.stat().st_size == 0:
        raise RuntimeError(f"Failed to materialize calibration increments: {increments_path}")
    emit(f"Wrote {increments_path} ({increments_path.stat().st_size:,} bytes)")

    outputs = [
        raw_dir / "calibration_events.parquet",
        raw_dir / "candidate_events.parquet",
        cal_dir / "eth_reference.parquet",
        cand_dir / "eth_reference.parquet",
        cal_dir / "aave_base_usdc_apy.parquet",
        cand_dir / "aave_base_usdc_apy.parquet",
        cal_dir / "hyperliquid_eth_funding.parquet",
        cand_dir / "hyperliquid_eth_funding.parquet",
        cal_dir / "excess_increments.parquet",
    ]
    sources = {
        "bulk_historical_source": historical_source,
        "pool_events": (
            "Envio HyperSync Base / Uniswap v3 pool logs"
            if historical_source == "HYPERSYNC"
            else "Base JSON-RPC / Uniswap v3 pool logs"
        ),
        "reference": "Binance public ETHUSDC aggregate-trade + 5m-kline archives",
        "benchmark": (
            "Aave v3 Base initial reserve state via RPC + ReserveDataUpdated via Envio HyperSync"
            if historical_source == "HYPERSYNC"
            else "Aave v3 Base on-chain ReserveDataUpdated + historical data-provider state via RPC"
        ),
        "funding": "Hyperliquid public fundingHistory info endpoint",
        "rpc_role": (
            "state_validation_and_block_boundaries_only"
            if historical_source == "HYPERSYNC"
            else "historical_logs_and_state"
        ),
    }
    if historical_source == "HYPERSYNC":
        sources["hypersync_url"] = hypersync_settings.url
        sources["hypersync_chain_id"] = hypersync_status.get("chain_id") if hypersync_status else None
        sources["hypersync_archive_height"] = hypersync_status.get("archive_height") if hypersync_status else None
    else:
        sources["rpc_effective_log_chunk_blocks"] = int(effective_chunk_blocks)

    manifest = {
        "schema_version": 2,
        "experiment_id": cfg["experiment_id"],
        "spec_sha256": canonical_hash(cfg),
        "outcome_blind": True,
        "candidate_primary_pnl_opened": False,
        "windows": {
            "calibration": {"start": cal_start.isoformat(), "end": cal_end.isoformat(), "from_block": ranges["calibration"][0], "to_block": ranges["calibration"][1]},
            "candidate": {"start": cand_start.isoformat(), "end": cand_end.isoformat(), "from_block": ranges["candidate"][0], "to_block": ranges["candidate"][1]},
        },
        "sources": sources,
        "outputs": {p.relative_to(root).as_posix(): _artifact_meta(p) for p in outputs},
    }
    manifest_path = root / "v015_acquisition_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def finalize_existing_v015_acquisition(cfg: dict, output_root: str | Path = "data") -> dict:
    """Build/refresh the outcome-blind acquisition manifest from existing artifacts.

    This is used after recovering from an interrupted acquisition where all raw
    datasets were already downloaded and only derived calibration increments were
    missing.  It never opens candidate-primary LP P&L.
    """
    root=Path(output_root).expanduser().resolve()
    cal_dir=root/"calibration"; cand_dir=root/"candidate"; raw_dir=root/"raw"
    outputs=[
        raw_dir/"calibration_events.parquet", raw_dir/"candidate_events.parquet",
        cal_dir/"eth_reference.parquet", cand_dir/"eth_reference.parquet",
        cal_dir/"aave_base_usdc_apy.parquet", cand_dir/"aave_base_usdc_apy.parquet",
        cal_dir/"hyperliquid_eth_funding.parquet", cand_dir/"hyperliquid_eth_funding.parquet",
        cal_dir/"excess_increments.parquet",
    ]
    missing=[str(p) for p in outputs if not p.exists() or artifact_size(p)<=0]
    if missing:
        raise RuntimeError("Cannot finalize acquisition; missing/empty artifacts: "+", ".join(missing))
    historical_source=str(cfg.get("historical_data",{}).get("event_source","RPC")).upper()
    cal_start,cal_end=_window(cfg,"calibration_window"); cand_start,cand_end=_window(cfg,"candidate_primary_window")
    windows={}
    for name,start,end in [("calibration",cal_start,cal_end),("candidate",cand_start,cand_end)]:
        ds=raw_dir/f"{name}_events.parquet"; success=ds/"_SUCCESS.json"
        meta=json.loads(success.read_text(encoding="utf-8")) if success.exists() else {}
        windows[name]={"start":start.isoformat(),"end":end.isoformat(),"from_block":meta.get("from_block"),"to_block":meta.get("to_block")}
    sources={
        "bulk_historical_source":historical_source,
        "pool_events":"Envio HyperSync Base / Uniswap v3 pool logs" if historical_source=="HYPERSYNC" else "Base JSON-RPC / Uniswap v3 pool logs",
        "reference":"Binance public ETHUSDC aggregate-trade + 5m-kline archives",
        "benchmark":"Aave v3 Base initial reserve state via RPC + ReserveDataUpdated via Envio HyperSync" if historical_source=="HYPERSYNC" else "Aave v3 Base on-chain ReserveDataUpdated + historical data-provider state via RPC",
        "funding":"Hyperliquid public fundingHistory info endpoint",
        "rpc_role":"state_validation_and_block_boundaries_only" if historical_source=="HYPERSYNC" else "historical_logs_and_state",
    }
    if historical_source=="HYPERSYNC":
        h=cfg.get("historical_data",{}).get("hypersync",{})
        sources["hypersync_url"]=h.get("url")
        sources["hypersync_chain_id"]=h.get("require_chain_id")
    manifest={
        "schema_version":3,"experiment_id":cfg["experiment_id"],"spec_sha256":canonical_hash(cfg),
        "outcome_blind":True,"candidate_primary_pnl_opened":False,"windows":windows,"sources":sources,
        "outputs":{p.relative_to(root).as_posix():_artifact_meta(p) for p in outputs},
        "recovered_from_existing_artifacts":True,
    }
    path=root/"v015_acquisition_manifest.json"; path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest
