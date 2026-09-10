# Changelog

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
