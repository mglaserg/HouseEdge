# HouseEdge LP v0.1.5

HouseEdge is the crypto/DEX “be the casino” research project: earn compensation for warehousing risk instead of relying on directional forecasts. **HouseEdge LP** is the first sleeve.

v0.1.5 is a governance/calibration patch over the v0.1.0 scaffold. It deliberately does **not** open Experiment 001. Its job is to make the eventual Base / Uniswap v3 WETH-USDC experiment falsifiable before primary LP P&L is inspected.

## Core rule

```text
Counterparty -> Compensation -> Costs -> Falsifier -> EdgeLab -> Build
```

A KILL is a successful research outcome. A measurement failure is VOID, not KILL. Range optimization cannot rescue a primary KILL.

## What changed in v0.1.5

- v0.1 Experiment 001 decision spec is superseded; the new spec starts as `CALIBRATION_REQUIRED`.
- Prospective power analysis is required before primary dates are frozen.
- ETH realized-volatility regime coverage is checked before the primary window is chosen.
- Gate 0 now compares fee capture and predictable LVR on the **same hypothetical concentrated-liquidity position** and uses mean realized variance `E[sigma^2]`.
- Uniswap v3 `SetFeeProtocol` events are archived and LP protocol-fee share can vary swap-by-swap.
- Short-lived/JIT liquidity has an explicit early diagnostic.
- Primary CEX alignment is frozen to the **last non-stale bid/ask midpoint at or before the Base block timestamp**.
- Primary hedge policy is 5% of LP NAV residual ETH delta, rebalance to zero; actual historical funding is required for a real run.
- Primary performance is **excess over the precommitted on-chain cash benchmark** (Aave v3 Base USDC), not raw return and not “risk-free” return.
- GO requires statistical significance, >=5% annualized excess return, and >=$10,000/year passive-counterfactual economic capacity.
- VOID criteria and micro-live fee-reconciliation threshold are explicit.
- Prediction files are SHA-256 sealed before the primary replay.
- Every post-unblind rerun is automatically counted as a new outcome look/trial.

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

### 3. Freeze calibration-only assumptions and prepare inputs

Before running power, choose the ETH perpetual hedge venue and its expected funding interval in `configs/experiment_001.yaml`, and fill the outcome-blind Gate-0 variable/fixed cost assumptions. These affect the noise/economic hurdle and are bound into the calibration hash.

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

### 4. Fill only the selected primary dates

Only after calibration passes:

- copy the exact candidate-window `start` / `end` emitted by the passing calibration report into `sample.start` / `sample.end`;
- set `status: READY_TO_FREEZE`.

Freeze verifies that all other calibration assumptions still hash to the passing report. Changing the hedge venue, costs, power settings, regime rules, benchmark, or capacity hurdle requires a new calibration run.

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

v0.1.5 prepares the governance, but **v0.2 still owes exact replay-state reconciliation and complete real-data funding/cost ingestion**. The primary runner is intentionally incapable of returning GO unless measurement validity is supplied.

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

The primary reference alignment is backward-only: no quote after the Base block timestamp can be used as the contemporaneous fair-price observation.

## JIT liquidity

`research/jit.py` FIFO-matches short-lived Mint/Burn lots by owner/range and measures overlap with swaps. This is intentionally labeled a diagnostic because pool events alone do not uniquely identify all economic NFT positions.

## Protocol fees

Do not hard-code “LPs keep 75%.” v0.1.5 reads the pool’s packed historical `feeProtocol` state and applies the relevant token0/token1 protocol denominator to each swap.

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
