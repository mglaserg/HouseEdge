# HouseEdge LP v0.1.8

HouseEdge is the crypto/DEX “be the casino” research project: earn compensation for warehousing risk instead of relying on directional forecasts. **HouseEdge LP** is the first sleeve.

v0.1.8 is the portable outcome-blind data-acquisition release over the frozen v0.1.6 Experiment 001 design. It deliberately does **not** open the candidate-primary LP outcome. Its job is to make the full v0.15 calibration reproducible from public/on-chain data on Lubuntu.

## Core rule

```text
Counterparty -> Compensation -> Costs -> Falsifier -> EdgeLab -> Build
```

A KILL is a successful research outcome. A measurement failure is VOID, not KILL. Range optimization cannot rescue a primary KILL.

## What changed in v0.1.8

- Make Binance archive timestamp matching resolution-independent across pandas 2.x/3.x by converting explicitly to Unix microseconds.
- Normalize acquisition-manifest output paths to POSIX form on every OS.

- Add `houseedge fetch-calibration-data`, which automatically builds every real-data file consumed by `calibrate-design`.
- Resolve the preregistered calibration/candidate UTC windows to Base block ranges by binary search.
- Pull calibration and candidate Uniswap v3 `Swap`, `Mint`, `Burn`, and `SetFeeProtocol` events and reconstruct historical protocol-fee state.
- Use Binance public ETH/USDC monthly archives: sparse aggregate-trade rows for the exact backward-only reference and 5-minute klines strictly for outcome-blind realized-volatility/regime measurement.
- Reconstruct Aave v3 Base USDC supply APY directly from on-chain `ReserveDataUpdated` events plus the historical rate at the window start; no third-party benchmark API is required.
- Fetch complete Hyperliquid ETH funding history with documented pagination.
- Replay **only the separate calibration window** to produce `excess_increments.parquet` for prospective power. Candidate-primary hedged LP P&L is never computed by acquisition.
- Write `data/v015_acquisition_manifest.json` with source descriptions, block ranges, config hash, file hashes, and `candidate_primary_pnl_opened: false`.
- Add explicit reference-row roles so 5-minute regime klines can never masquerade as fresh trade-tape observations in the primary timestamp-alignment rule.

## Frozen v0.1.6 design retained

- Freeze Experiment 001 to the Base Uniswap v3 WETH/USDC 5 bp pool at `0xd0b53d9277642d899df5c87a3966a349a798f224`.
- Precommit the calibration window to 2025-07-01..2025-12-31 and the candidate primary window to 2026-01-01..2026-08-31.
- Precommit Hyperliquid ETH perpetual as the hedge venue, 5.0 bp taker+slippage cost, 1-hour funding cadence, 5% NAV delta trigger, and rebalance-to-zero policy.
- Precommit Gate-0 variable friction at 2.5%/yr plus $100/yr fixed cost.
- Change the primary historical fair-value convention to Binance spot ETH/USDC **last trade at or before the Base block timestamp**, max age 3 seconds. No look-ahead is allowed.
- Replace the arbitrary 100-swap stationary-bootstrap block with an outcome-blind calibration-derived dependence length. The calibration report selects the block length and freeze verifies that exact value.
- Add `houseedge prepare-freeze` to apply only the passing calibration report's selected dates and bootstrap block length to the YAML.
- Historical trade-tape reference inputs may now provide `price` or `last_trade` instead of bid/ask midpoint columns.

All other v0.1.5 governance remains in force: power, regime coverage, same-basis Gate 0, historical protocol fees, JIT diagnostics, Aave Base USDC cash benchmark, statistical/economic/capacity hurdles, VOID rules, micro-live reconciliation, sealed prediction, and post-unblind look counting.

## Install

Python 3.11+ is supported. The project is designed around `uv`.

```bash
uv sync --extra dev
```

## v0.15 workflow

### 1. Discover the Base WETH/USDC 5 bp pool

```bash
houseedge discover-pool
```

### 2. Acquire all outcome-blind v0.15 data

For the multi-month Base log pull, set an archive/log-capable Base RPC. The public Base RPC is useful for plumbing but is not appropriate for this workload.

```bash
export BASE_RPC_URL="https://YOUR_ARCHIVE_CAPABLE_BASE_RPC"

uv run houseedge fetch-calibration-data
```

This automatically writes:

```text
data/calibration/excess_increments.parquet
data/calibration/eth_reference.parquet
data/calibration/aave_base_usdc_apy.parquet
data/calibration/hyperliquid_eth_funding.parquet
data/candidate/eth_reference.parquet
data/candidate/aave_base_usdc_apy.parquet
data/candidate/hyperliquid_eth_funding.parquet
data/raw/calibration_events.parquet
data/raw/candidate_events.parquet
data/v015_acquisition_manifest.json
```

The Binance archive cache is retained under `data/cache/binance/`, so rerunning the command does not redownload existing monthly ZIPs unless `--force-downloads` is supplied.

Candidate-primary LP P&L is **not** computed by this command. Only the separate 2025 calibration window is replayed to estimate the noise/dependence process for prospective power.

### 3. Run v0.15 design calibration

```bash
uv run houseedge calibrate-design \
  --calibration-increments data/calibration/excess_increments.parquet \
  --calibration-reference data/calibration/eth_reference.parquet \
  --candidate-reference data/candidate/eth_reference.parquet \
  --candidate-events data/raw/candidate_events.parquet \
  --benchmark-rates data/candidate/aave_base_usdc_apy.parquet \
  --output runs/v015_calibration
```

A calibration `PASS` is permission to freeze a test, not evidence that LP edge exists.

### 4. Apply the calibration-selected fields

Only after calibration passes:

```bash
houseedge prepare-freeze \
  --calibration-report runs/v015_calibration/calibration_report.json
```

This writes only the exact candidate-window `start` / `end`, the calibration-derived stationary-bootstrap mean block length, and `status: READY_TO_FREEZE`. Freeze verifies that all other calibration assumptions still hash to the passing report. Changing the hedge venue, costs, power settings, regime rules, benchmark, reference convention, or capacity hurdle requires a new calibration run.

### 5. Seal the prior prediction

Fill `prereg/experiment_001_prediction.json` with the expected point estimate, CI, capacity and predicted decision, then:

```bash
houseedge seal-prediction
```

### 6. Freeze Experiment 001

```bash
houseedge freeze \
  --calibration-report runs/v015_calibration/calibration_report.json
```

Freeze refuses to proceed if calibration did not pass, the spec is not `READY_TO_FREEZE`, or the prediction hash is not in the local prediction registry.

## Eventual v0.2 primary run

v0.1.8 prepares governance **and acquires the v0.15 real-data inputs**, but **v0.2 still owes exact primary replay-state reconciliation and final real-data cost execution**. The primary runner is intentionally incapable of returning GO unless measurement validity is supplied.

The frozen outcome will use:

```text
Net discrete-delta-hedged LP return
- time-matched on-chain cash benchmark
= primary excess return
```

GO requires all of:

```text
lower 95% stationary-bootstrap CI of annualized excess > 0
point estimate annualized excess >= 5%
passive capacity supports >= $10,000/year expected excess profit
micro-live fee reconciliation passes
all VOID criteria pass
```

Otherwise the result is KILL or VOID as appropriate.

## Markouts

30s / 60s / 5m markouts remain **flow-quality diagnostics only**. They are not LVR and are never subtracted from fees to form the primary P&L statistic.

The primary historical reference is Binance spot ETH/USDC trade tape. The contemporaneous value is the last non-stale trade at or before the Base block timestamp (max age 3 seconds); no later trade can be used. Alternative midpoint/composite references are sensitivity diagnostics only.

## JIT liquidity

`research/jit.py` FIFO-matches short-lived Mint/Burn lots by owner/range and measures overlap with swaps. This is intentionally labeled a diagnostic because pool events alone do not uniquely identify all economic NFT positions.

## Protocol fees

Do not hard-code “LPs keep 75%.” v0.1.8 reads the pool’s packed historical `feeProtocol` state and applies the relevant token0/token1 protocol denominator to each swap.

## Synthetic demo

```bash
houseedge demo
```

This validates plumbing only and uses a separate synthetic config. It never freezes or spends the real experiment.

## Dashboard

The dashboard remains read-only and separate from research/runner processes:

```bash
uv run streamlit run dashboard/app.py
```

## Safety / execution scope

There are no private-key fields, wallet signers, transaction broadcasters, or live LP execution controls in this release. The micro-live pilot is a later telemetry/reconciliation task after v0.15 selects a viable minimum size; it is not part of the primary statistical sample.

### Base RPC preflight (v0.1.9+)

Before the multi-month v0.15 backfill, probe the configured RPC:

```bash
uv run houseedge rpc-preflight
```

HouseEdge intentionally refuses a very large historical acquisition if the endpoint only accepts ~10 blocks per `eth_getLogs` request. This is common on restricted/free RPC tiers and would require millions of calls for Experiment 001. Use a provider/tier with materially larger historical log ranges. The acquisition path still retries and recursively splits occasional oversized/result-heavy ranges.
