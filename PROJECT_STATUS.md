# HouseEdge project status

**Canonical status date:** 2026-09-21  
**Current release baseline:** v0.2.6  
**Experiment 001 state:** `CALIBRATION_REQUIRED`  
**Primary outcome state:** no checked-in result; outcome-blind paths explicitly assert it remains unopened

This file answers **what is true now**. `ROADMAP.md` answers **what comes next**.

## North star

HouseEdge should answer:

> Does passive concentrated liquidity provision earn a statistically positive, economically meaningful, and capacity-viable excess return after adverse selection, discrete hedging, funding, protocol fees, operating costs, and a time-matched on-chain cash alternative?

The first registered test is HouseEdge LP Experiment 001 on the Base Uniswap v3 WETH/USDC 5 bp pool.

## Implemented now

### Research governance

- Machine-readable Experiment 001 configuration and EdgeLab manifest.
- Outcome-blind calibration basis hashing.
- Prediction sealing, preregistration freeze validation, and append-only outcome-look accounting.
- Explicit `GO` / `KILL` / `VOID` decision semantics.
- Pre-outcome checks for reference coverage, funding gaps, protocol-fee history, replay-state validity, and micro-live reconciliation.

### Data acquisition and provenance

- Envio HyperSync acquisition for Base Uniswap v3 `Swap`, `Mint`, `Burn`, and `SetFeeProtocol` history.
- Bounded, resumable block-chunk datasets with per-part checkpoints and `_SUCCESS.json` completion markers.
- Sparse Base RPC use for timestamp/block boundaries and historical state seeds.
- Deterministic Binance-primary/Bybit-fallback spot reference construction with backward-only matching.
- Aave v3 Base USDC benchmark history and Hyperliquid ETH funding history.
- Artifact size/hash accounting and an outcome-blind acquisition manifest.
- Wide EVM integer preservation at the Parquet boundary.
- One-command reference rebuilding from existing Base event parts, without HyperSync redownload or candidate-primary P&L access.
- A governed reference contract across config, tests, README, preregistration, and hashing: fixed venue priority, calibration-only selection from the predeclared freshness grid, and candidate-only out-of-sample evaluation against the unchanged 0.5% maximum-missing gate.

### Calibration and research engine

- Stateful partition-by-partition LP/hedge replay for calibration noise derivation.
- UTC-daily excess-return increments for dependence and power analysis.
- Prospective power, regime coverage, Gate 0 economics, JIT diagnostics, and passive capacity analysis.
- Calibration-selected stationary-bootstrap mean block length in days.
- Historical protocol-fee reconstruction.
- Backward reference alignment plus time-shift diagnostics.
- Markouts and shuffled-direction null diagnostics.
- Discrete delta-hedged LP replay with hedge costs, funding, benchmark return, bootstrap inference, and capacity gates.

### Interfaces

- Typer CLI for acquisition, diagnostics, calibration, freeze governance, synthetic demo, and guarded primary execution.
- Read-only Streamlit dashboard for run artifacts.
- Synthetic demo path that is isolated from the primary preregistration.

## What is not complete

- A passing v0.15 calibration report is not checked into the repository.
- `configs/experiment_001.yaml` has not transitioned to `READY_TO_FREEZE`.
- `prereg/experiment_001_prediction.json` remains an unsealed template.
- The primary specification is not frozen.
- Exact primary replay-state reconciliation evidence is not present.
- The preregistered micro-live fee-reconciliation pilot is not implemented as a live execution system and no passing report is present.
- No primary `GO`, `KILL`, or `VOID` result has been produced or claimed.
- No real candidate reference-coverage verdict has been produced in this checkout because the ignored Base event artifacts are absent.
- The dashboard is an artifact viewer, not a complete experiment-control surface.
- This checkout currently has none of the required v0.15 calibration/candidate artifacts and has no configured `ENVIO_API_TOKEN` or `BASE_RPC_URL`.

## Current objective — complete v0.15 without unblinding

The next coherent slice is to acquire or restore, then audit, the outcome-blind design-calibration inputs:

1. Configure `ENVIO_API_TOKEN` and an archive-capable `BASE_RPC_URL`, or restore the complete existing `data/` artifact tree.
2. Run `houseedge hypersync-preflight` before starting a new download.
3. Acquire/resume with `fetch-calibration-data`, reusing completed checkpoints rather than restarting them.
4. Run `houseedge rebuild-references` against the restored event parts. Accept its calibration-selected policy and candidate coverage verdict without changing the 0.5% gate.
5. Rebuild calibration increments with `derive-calibration-increments --force` under the selected reference policy.
6. Run bounded-memory `calibrate-design` and retain its report outside Git unless intentionally promoted as a fixture.
7. If and only if the report is `PASS`, apply the exact selected dates/block length with `prepare-freeze`.
8. Fill and seal the prior prediction before freezing.

The next command should be chosen from artifact state; do not blindly restart acquisition when completed checkpoints can be reused.

## Reference-feasibility governance

Experiment 001 spec v0.2.2 supersedes the brittle fixed three-second single-Binance reference before freeze. Binance and Bybit spot last trades are combined by fixed priority; every observation is backward-only. Only calibration coverage may select the smallest passing age from `[1, 2, 3, 5, 10]` seconds. Candidate coverage is a validity check, not a tuning input. The 0.5% maximum-missing rule is unchanged.

The selected policy has a dedicated hash and is also bound into the calibration-basis hash. The report digest is provenance and is deliberately excluded from the basis to avoid recursive hashing.

## Pre-freeze consistency audit

Earlier naming and timestamp consistency issues were resolved on 2026-09-21. The later v0.2.2 reference-feasibility amendment intentionally changes the config and calibration-basis hash before freeze, while the primary outcome remains unopened:

- Git history confirms v0.1.6 deliberately selected backward last trade and commit `10df22e` deliberately selected Binance `ETHUSDT` while calibration was still required.
- Config, preregistration, README, and regression tests now describe the same ETH/USDT last-trade rule.
- The pandas 3 mixed-resolution failure is fixed at the future-markout as-of boundary, matching primary alignment's UTC-nanosecond normalization.
- Acquisition output prints its absolute root as one plain-text line so CI/test terminals cannot split the machine-verifiable path.

Generated repair/calibration reports still live under ignored paths, so their presence and outcome cannot be inferred from Git history alone. No such artifacts are present in this checkout.

## Verification snapshot

Verified on 2026-09-21:

- `uv run pytest` and `uv run ruff check .` could not start because `uv` is not installed on this host.
- The broken `.venv` interpreter points at a removed system Python, but its site packages were reusable with the available Python 3.12 runtime. Under that bridge, the full suite passed: **56 tests passed**.
- Focused regression coverage passed for multi-venue priority/fallback behavior, backward-only observations, calibration-only freshness selection, candidate out-of-sample evaluation, CLI reporting, reference alignment, markouts, acquisition failure output, and the Experiment 001 config contract.
- The available Ruff binary reports 104 pre-existing repository-wide findings across application, script, and test files; the new multi-venue provider/policy modules, wrapper, and tests pass focused Ruff checks.

The test baseline is green. The repository-wide Ruff baseline is not; recreate the development environment with `uv sync --extra dev` and address the existing lint debt as a separate mechanical cleanup.

## Recommended next files

For the current milestone, start with provider setup or restoration of the ignored artifacts, then use:

```text
src/houseedge/data/acquire.py
src/houseedge/data/fair_value.py
src/houseedge/data/bybit_public.py
src/houseedge/data/hypersync_base.py
data/v015_acquisition_status.json
data/v015_acquisition_manifest.json
runs/v015_reference_feasibility.json
data/raw/{calibration,candidate}_events.parquet/
data/{calibration,candidate}/
src/houseedge/calibration.py
runs/v015_calibration/calibration_report.json
```

Do not touch `src/houseedge/experiment.py` merely to make a calibration gate pass. A failed design gate is information, not a software defect.
