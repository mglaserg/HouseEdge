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
- Binance public archive reference construction with backward-only matching.
- Aave v3 Base USDC benchmark history and Hyperliquid ETH funding history.
- Artifact size/hash accounting and an outcome-blind acquisition manifest.
- Wide EVM integer preservation at the Parquet boundary.
- Targeted reference refresh, tolerance analysis, and daily-archive candidate-reference repair tools.

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
- The dashboard is an artifact viewer, not a complete experiment-control surface.

## Current objective — complete v0.15 without unblinding

The next coherent slice is to finish and audit the outcome-blind design-calibration path:

1. Verify calibration and candidate artifact completeness and hashes.
2. Verify actual backward reference merge coverage under the configured tolerance.
3. Resolve the open specification consistency issues below without inspecting candidate-primary LP P&L.
4. Run bounded-memory `calibrate-design` and retain its report outside Git unless intentionally promoted as a fixture.
5. If and only if the report is `PASS`, apply the exact selected dates/block length with `prepare-freeze`.
6. Fill and seal the prior prediction before freezing.

The next command should be chosen from artifact state; do not blindly restart acquisition when completed checkpoints can be reused.

## Open consistency issues before freeze

These are governance issues, not license to pick the most convenient value:

- The active config uses `primary_reference_symbol: ETHUSDT`, while older tests/text still contain `ETHUSDC` expectations.
- The active config and README specify a backward **last-trade** reference, while `prereg/experiment_001.md` still contains an older bid/ask-midpoint sentence.
- Generated repair/calibration reports live under ignored paths, so their presence and outcome cannot be inferred from Git history alone.

Reconcile the intended rule across config, preregistration, tests, and docs before freeze. If the resolution changes an assumption included in the calibration basis hash, rerun calibration.

## Verification snapshot

Attempted on 2026-09-21:

- `uv run pytest` and `uv run ruff check .` could not start because `uv` is not installed on this host.
- The broken `.venv` interpreter points at a removed system Python, but its site packages were reusable with the bundled Python 3.12 runtime. Under that bridge, pytest collected 48 tests: **45 passed and 3 failed**.
- The three observed failures are: Rich console line-wrapping makes the absolute-output assertion platform-width dependent; `test_experiment001_config.py` still expects `ETHUSDC` while the active config says `ETHUSDT`; and pandas 3 preserves mismatched `datetime64[ns]`/`datetime64[us]` units in the markout as-of join.
- The available Ruff binary completed and reported 105 pre-existing findings across application, script, and test files. Documentation-only changes did not modify those files.

The current baseline is therefore not green. Recreate the development environment with `uv sync --extra dev`, then resolve or explicitly baseline the three test failures and lint debt before treating it as green.

## Recommended next files

For the current milestone, start with:

```text
configs/experiment_001.yaml
prereg/experiment_001.md
prereg/experiment_001_prediction.json
scripts/repair_candidate_reference.py
src/houseedge/calibration.py
src/houseedge/prereg.py
tests/test_experiment001_config.py
tests/test_alignment.py
tests/test_prereg.py
```

Do not touch `src/houseedge/experiment.py` merely to make a calibration gate pass. A failed design gate is information, not a software defect.
