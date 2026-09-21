# Unreleased

- Replace the single-Binance primary reference with a deterministic backward-only Binance spot ETHUSDT primary and Bybit spot ETHUSDT fallback.
- Select the smallest preregistered freshness in `[1, 2, 3, 5, 10]` seconds using calibration coverage only; candidate data can only pass or fail the unchanged 0.5% maximum-missing gate.
- Add `houseedge rebuild-references` to reuse existing Base event parts, rebuild both reference files, refresh hashes/provenance, and report the out-of-sample validity result without candidate-primary LP P&L or HyperSync downloads.
- Bind the selected reference policy into calibration reports, basis hashing, and freeze validation, with backward/no-lookahead and outcome-blind regression coverage.
- Add canonical agent guidance, project status, capability roadmap, architecture, development documentation, and an ADR process modeled on the durable project-memory structure used by VolForge.
- Document the outcome-blind calibration/primary boundary, experiment state machine, package ownership, storage contracts, verification baseline, and pre-freeze specification consistency checks.
- Link the project documentation set from the README.
- Add a regression test that requires the canonical documentation set and verifies its local Markdown links.
- Reconcile Experiment 001's stale prose/tests with the already-configured Binance ETH/USDT backward last-trade reference without changing the config or calibration-basis hash.
- Normalize future-markout as-of joins to UTC nanoseconds, matching primary alignment and restoring pandas 3 timestamp-unit portability.
- Emit the acquisition output root as a non-wrapping plain-text line for reliable logs and CLI assertions.

# v0.2.6

- Add `houseedge derive-calibration-increments` to recover from a completed HyperSync backfill without redownloading any Base, Binance, Aave, or Hyperliquid history.
- Replace the six-month in-memory calibration replay with a stateful partition-by-partition replay that carries LP inventory, hedge state, funding intervals, and final hedge close across Parquet chunks.
- Aggregate calibration power noise to UTC daily excess-return increments, matching the intended dependent daily P&L process instead of treating raw swaps as independent observations.
- Make `calibrate-design` process partitioned candidate event history in bounded memory for reference alignment, Gate-0 economics, JIT diagnostics, and capacity analysis.
- Switch prospective and primary stationary-bootstrap inference to calibration-selected mean block length in **days** rather than swaps.
- Add recovery finalization: after the missing increments are derived, HouseEdge verifies all v0.15 artifacts, rebuilds the outcome-blind manifest, and marks acquisition `COMPLETE` without opening candidate-primary P&L.
- No candidate-primary hedged LP outcome is opened by this release.

# v0.2.5

- Chunk Aave v3 Base `ReserveDataUpdated` HyperSync history using the same bounded 100k-block windows as Uniswap acquisition.
- Add outer retry with exponential backoff for truncated/interrupted HyperSync Arrow responses so only the failed Aave chunk is retried instead of the full multi-month window.
- Emit Aave block-range progress during calibration acquisition.
- No Experiment 001 economics, preregistration, or outcome logic changed.

## v0.2.4

- Fix Experiment 001 acquisition failing with `Python int too large to convert to C long` when Parquet/Arrow encounters Uniswap/Aave EVM integers wider than signed int64.
- Serialize arbitrary-precision EVM integer columns losslessly as decimal strings at the Parquet boundary; downstream HouseEdge math converts them explicitly when needed.
- Covers uint160 `sqrtPriceX96`, uint128 liquidity, int/uint256 raw amounts, Aave ray values, and future oversized integer fields generically rather than hard-coding one column.
- Adds regression tests for dense and sparse wide-integer columns.
- No Experiment 001 economics, preregistration, outcome window, or decision rule changed.

## v0.2.3

- Fixes the Lubuntu acquisition process being killable before its first write by removing the whole-window HyperSync event buffer from Experiment 001 acquisition.
- Uniswap event history is now fetched in bounded block chunks and written immediately as resumable partitioned Parquet datasets.
- Interrupted or OOM-killed acquisitions keep completed `part-*.parquet` files and resume them on the next run.
- Adds stable hashing/size accounting for partitioned dataset artifacts and explicit `_SUCCESS.json` markers.
- No Experiment 001 hypothesis, hedge, economic hurdle, or outcome logic changed.

# Changelog

## v0.2.2
- Make `fetch-calibration-data` resolve and print an absolute output directory before work starts.
- Write `v015_acquisition_status.json` immediately, with COMPLETE/FAILED terminal state.
- Verify every acquisition artifact exists and is non-empty before reporting success.
- Emit a message after each Parquet artifact is actually materialized.
- Make dataframe writes atomic via temporary file + replace.

# HouseEdge Changelog

## v0.2.1 — HyperSync hex normalization + .env loading

- Normalize every HyperSync query address/topic to canonical `0x`-prefixed fixed-width Ethereum hex.
- Fix `event_topic0()` for dependency versions where `HexBytes.hex()` returns bare hex, preventing HyperSync `parse query ... invalid hex prefix` failures.
- Normalize decoded event topic lookup through the same helper.
- Load project/local `.env` automatically at CLI startup with a dependency-free loader; shell environment variables take precedence.
- Add regression tests for bare-hex HyperSync inputs and event signatures.

## 0.2.0 — HyperSync historical ingestion

- Make Envio HyperSync the default bulk historical source for Base Uniswap v3 logs in Experiment 001.
- Move Aave v3 Base `ReserveDataUpdated` history to HyperSync as well; RPC is used only to seed the starting historical state.
- Add `houseedge hypersync-preflight` and require Base chain id 8453 before acquisition.
- Keep keyed Base RPC for block-window resolution and sparse historical `eth_call` state reads; restricted `eth_getLogs` tiers no longer block the normal workflow.
- Do not silently fall back to RPC bulk logs: `historical_data.rpc_fallback_allowed` remains false for Experiment 001.
- Upgrade the acquisition manifest to schema v2 with historical-source provenance while never persisting the Envio API token.
- Add HyperSync client/query fixtures and a regression test proving HyperSync acquisition never invokes the RPC log-range probe.
- No Experiment 001 economic hurdle, hedge rule, primary reference convention, or outcome-blindness rule changed.


## 0.1.9 - 2026-09-08
- Add `houseedge rpc-preflight` to probe Base RPC `eth_getLogs` range capability before a historical backfill.
- Fail fast when a provider behaves like Alchemy Free's 10-block log tier instead of launching millions of RPC requests.
- Add retry + recursive range splitting for result-heavy/intermittently rejected event-log requests.
- Apply resilient log fetching to both Uniswap v3 and Aave benchmark event histories.
- Record the effective RPC log chunk size in the v0.15 acquisition manifest.
- No Experiment 001 economics, preregistered hurdle, primary window, or hedge rule changed.

## 0.1.8 — Binance timestamp portability fix

- Fix Binance aggregate-trade target matching on environments where pandas preserves `datetime64[us]` resolution (notably pandas 3.x).
- Convert all sparse-reference target/month-boundary timestamps explicitly to Unix microseconds instead of assuming nanosecond-backed integers.
- Normalize acquisition-manifest output keys to POSIX paths so Windows and Linux produce the same auditable manifest schema.
- Add an explicit microsecond-resolution regression test; full suite expands to 26 tests.
- No Experiment 001 economic/governance rules changed; candidate-primary LP P&L remains unopened.

## 0.1.7 — Outcome-blind calibration data acquisition

- Add one-command `fetch-calibration-data` acquisition for the complete v0.15 input set.
- Resolve preregistered UTC windows to Base blocks without outcome inspection.
- Pull calibration/candidate Uniswap v3 event tapes and reconstruct historical protocol-fee state.
- Add sparse Binance ETH/USDC aggregate-trade reference extraction plus separate 5-minute regime data from official public archives.
- Add on-chain Aave v3 Base USDC supply-rate reconstruction.
- Add paginated Hyperliquid ETH historical funding acquisition.
- Derive power/noise increments from the separate calibration window only; candidate-primary LP P&L remains unopened.
- Add an acquisition manifest with config hash, block ranges, output hashes, and an explicit outcome-blind flag.
- Add reference-role flags so regime-only observations cannot enter backward fair-value alignment.
- Expand tests to 25, covering archive reduction, reference-role isolation, Aave rate conversion, calibration-only increment derivation, and outcome-blind orchestration.


## 0.1.6 — Experiment 001 configuration freeze

- Freeze the Base WETH/USDC 5 bp pool address and outcome-blind calibration/candidate windows.
- Freeze Hyperliquid ETH perp hedge venue, 5 bp taker+slippage cost, 1-hour funding cadence, 5% NAV delta trigger, and rebalance-to-zero policy.
- Freeze Gate-0 variable/fixed cost assumptions at 2.5%/yr + $100/yr.
- Freeze the primary historical reference to backward-only Binance spot ETH/USDC last trades with a 3-second staleness limit.
- Replace the arbitrary 100-swap bootstrap block with a calibration-derived autocorrelation length, bounded to 5..1000 swaps.
- Bind the selected bootstrap block length to the passing calibration report and require an exact match at freeze.
- Add `houseedge prepare-freeze` to apply calibration-selected dates/block length without opening the primary outcome.
- Accept historical reference trade tapes with `price` or `last_trade` columns.
- Expand the test suite to cover the selected Experiment 001 config, trade-price reference normalization, serial-dependence block calibration, and prepare-freeze governance.

## 0.1.5 — v0.15 governance/calibration patch

- Supersede the v0.1 Experiment 001 decision configuration; primary outcome remains unopened.
- Add prospective stationary-bootstrap power analysis with separate statistical-detectability and full-GO power reporting.
- Add outcome-blind ETH realized-variance regime coverage checks before primary dates are frozen.
- Replace scalar Gate 0 as the primary screen with a same-position fee/LVR calculation using `E[sigma^2]` and hypothetical raw Uniswap liquidity.
- Add historical Uniswap v3 `SetFeeProtocol` ingestion, `slot0.feeProtocol` initialization, and swap-level LP fee fractions.
- Add JIT/short-lived-liquidity diagnostic.
- Freeze primary reference alignment to last non-stale bid/ask midpoint at or before block timestamp.
- Change primary hedge specification to a 5%-of-LP-NAV residual delta trigger and rebalance-to-zero policy; real runs require actual historical funding data.
- Add time-weighted on-chain cash benchmark integration and annualized excess-return inference.
- Add statistical + economic + capacity decision gates.
- Add VOID criteria and micro-live fee-reconciliation threshold.
- Add SHA-256 prediction sealing and freeze-time verification.
- Add automatic outcome-look registry; every post-unblind rerun is a new look.
- Add a separate synthetic demo config so plumbing validation cannot accidentally freeze or spend Experiment 001.
- Expand tests from 7 to 14, including protocol fees, backward-only alignment, benchmark accrual, power, JIT, VOID, and rerun counting.

## 0.1.0

- Initial HouseEdge LP Experiment 001 scaffold.
- Gate-0 screen, Base Uniswap v3 event ingestion, reference-price alignment, markouts/nulls, discrete hedge replay, stationary bootstrap, passive capacity sweep, synthetic demo, and separate read-only dashboard.
