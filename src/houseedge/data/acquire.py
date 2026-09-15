from __future__ import annotations

import hashlib
import json
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
from houseedge.data.storage import write_frame
from houseedge.research.alignment import align_reference
from houseedge.research.protocol_fee import attach_protocol_fee_state
from houseedge.research.replay import replay_discrete_hedged_lp


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    for name, (b0, b1) in ranges.items():
        if historical_source == "HYPERSYNC":
            from houseedge.data.hypersync_base import fetch_uniswap_v3_events
            emit(f"Fetching Base Uniswap v3 {name} events via HyperSync: {b0:,}..{b1:,}")
            ev = fetch_uniswap_v3_events(pool, spec, b0, b1, settings=hypersync_settings)
        else:
            emit(f"Fetching Base Uniswap v3 {name} events via RPC: {b0:,}..{b1:,}")
            ev = fetch_events(w3, pool, spec, b0, b1, chunk_blocks=int(effective_chunk_blocks), workers=workers)
        # Protocol-fee history is carried in SetFeeProtocol events; a single
        # historical RPC state read seeds the state immediately before each window.
        initial_fee = read_fee_protocol_at_block(w3, pool, max(0, b0 - 1))
        ev = attach_protocol_fee_state(ev, initial_fee)
        event_frames[name] = ev
        path = raw_dir / f"{name}_events.parquet"
        write_frame(ev, path)
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"Failed to materialize event artifact: {path}")
        emit(f"Wrote {path} ({path.stat().st_size:,} bytes)")

    symbol = "ETHUSDC"
    max_age = float(cfg["sample"]["primary_alignment"]["max_age_seconds"])
    references = {}
    for name, (start, end) in {"calibration": (cal_start, cal_end), "candidate": (cand_start, cand_end)}.items():
        emit(f"Downloading/scanning Binance {symbol} public archives for {name} reference")
        targets = event_frames[name].loc[event_frames[name]["event"].eq("Swap"), "timestamp"]
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
                w3, b0, b1, settings=hypersync_settings, asset=cfg["pool"]["token1_address"]
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

    emit("Deriving calibration-only excess-return increments for prospective power")
    increments = derive_calibration_excess_increments(
        event_frames["calibration"], references["calibration"], funding["calibration"], benchmarks["calibration"], cfg
    )
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
        "outputs": {p.relative_to(root).as_posix(): {"sha256": _sha256(p), "bytes": p.stat().st_size} for p in outputs},
    }
    manifest_path = root / "v015_acquisition_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
