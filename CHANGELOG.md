# Changelog

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
