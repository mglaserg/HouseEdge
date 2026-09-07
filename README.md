# HouseEdge LP v0.1.6

HouseEdge is the crypto/DEX “be the casino” research project: earn compensation for warehousing risk instead of relying on directional forecasts. **HouseEdge LP** is the first sleeve.

v0.1.6 is a configuration-freeze patch over the v0.1.5 governance scaffold. It deliberately does **not** open Experiment 001. Its job is to make the eventual Base / Uniswap v3 WETH-USDC experiment falsifiable before primary LP P&L is inspected.

## Core rule

```text
Counterparty -> Compensation -> Costs -> Falsifier -> EdgeLab -> Build
```

A KILL is a successful research outcome. A measurement failure is VOID, not KILL. Range optimization cannot rescue a primary KILL.

## What changed in v0.1.6

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

### 2. Fetch outcome-blind candidate-window pool events

Use an archive/log-capable Base RPC for historical work:

```bash
export BASE_RPC_URL="https://YOUR_BASE_RPC"
houseedge fetch-events \
  --from-block 12345678 \
  --to-block 12445678 \
  --output data/raw/candidate_events.parquet
```

`fetch-events` now archives `Swap`, `Mint`, `Burn`, and `SetFeeProtocol` in exact block / transaction / log order. It also reads `slot0.feeProtocol` at the block immediately preceding the requested window and attaches the historically correct LP fee fraction to each swap.

### 3. Prepare outcome-blind calibration inputs

v0.1.6 has already frozen the primary hedge venue/cost convention and Gate-0 cost assumptions in `configs/experiment_001.yaml`. These assumptions are bound into the calibration hash.

`houseedge calibrate-design` then expects:

- a **separate calibration** return-increment series with `excess_return_inc`, used only for dependence/noise and power;
- calibration ETH reference prices;
- candidate-window ETH reference prices;
- candidate-window pool events;
- the candidate-window Aave v3 Base USDC APY series (`timestamp,apy`).

The primary LP hedged P&L must not be inspected during this stage.

```bash
houseedge calibrate-design \
  --calibration-increments data/calibration/excess_increments.parquet \
  --calibration-reference data/calibration/eth_reference.parquet \
  --candidate-reference data/candidate/eth_reference.parquet \
  --candidate-events data/raw/candidate_events.parquet \
  --benchmark-rates data/candidate/aave_base_usdc_apy.parquet \
  --output runs/v015_calibration
```

The report includes:

- statistical power at a true +5% annual excess edge;
- full-GO power at a larger material alternative (default +8% because a point-estimate hurdle at +5% makes full-GO power at a true +5% edge structurally <=~50%);
- low/high realized-variance regime coverage;
- same-basis Gate-0 fee/LVR economics;
- JIT/short-lived-liquidity diagnostics;
- minimum-viable-size information;
- passive-counterfactual capacity prize.

A calibration `PASS` is permission to **freeze a test**, not evidence that LP edge exists.

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

v0.1.6 prepares the governance and freezes the remaining calibration choices, but **v0.2 still owes exact replay-state reconciliation and complete real-data funding/cost ingestion**. The primary runner is intentionally incapable of returning GO unless measurement validity is supplied.

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

Do not hard-code “LPs keep 75%.” v0.1.6 reads the pool’s packed historical `feeProtocol` state and applies the relevant token0/token1 protocol denominator to each swap.

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
