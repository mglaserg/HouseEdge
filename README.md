# HouseEdge LP v0.2.6

> **v0.2.6 bounded-memory calibration recovery:** HouseEdge can now derive the missing calibration power series directly from the already-downloaded partitioned Base event dataset, carrying LP/hedge state across chunks without loading six months of events into RAM. `calibrate-design` also streams the partitioned candidate event history instead of materializing it all at once.


HouseEdge is the crypto/DEX “be the casino” research project: earn compensation for warehousing risk instead of relying on directional forecasts. **HouseEdge LP** is the first sleeve.

v0.2.6 keeps HyperSync as the bulk Base history source and makes both acquisition **and v0.15 calibration** bounded-memory. Multi-month Uniswap event windows are checkpointed to partitioned Parquet; calibration replays those partitions sequentially, produces UTC-daily excess-return increments for power analysis, and streams candidate Gate-0/JIT/capacity diagnostics. Alchemy/Base RPC remains only for lightweight block-boundary and historical state reads. The release remains outcome-blind: it deliberately does **not** open the candidate-primary LP outcome.

### HyperSync transport resilience

Aave Base USDC benchmark history is fetched in the same bounded HyperSync block chunks as the Uniswap history. If an Arrow response is truncated or the transport drops, HouseEdge retries only the affected Aave chunk with exponential backoff rather than restarting the entire multi-month benchmark query.


## Core rule

```text
Counterparty -> Compensation -> Costs -> Falsifier -> EdgeLab -> Build
```

A KILL is a successful research outcome. A measurement failure is VOID, not KILL. Range optimization cannot rescue a primary KILL.

## What changed through v0.2.6

- Fetch Uniswap history in bounded HyperSync block chunks (`100000` blocks by default) instead of buffering an entire multi-month window in one Python list.
- Write each completed chunk immediately under `data/raw/{calibration,candidate}_events.parquet/part-*.parquet`, with per-chunk `.done.json` checkpoints and a final `_SUCCESS.json`.
- Resume completed chunks automatically after interruption; `--force-downloads` clears and rebuilds the dataset.
- Avoid loading calibration and candidate event histories into RAM together during acquisition; reference construction projects only `event` + `timestamp`.
- Update `v015_acquisition_status.json` on every progress checkpoint so a killed process leaves its last completed step behind.
- Make **Envio HyperSync** the default bulk historical source for Base Uniswap v3 `Swap`, `Mint`, `Burn`, and `SetFeeProtocol` logs.
- Use HyperSync for Aave v3 Base `ReserveDataUpdated` history as well, so the benchmark side cannot fall back into restricted multi-month `eth_getLogs` scans.
- Keep `BASE_RPC_URL` for timestamp-to-block boundary resolution and one historical state seed read per window (Uniswap `slot0.feeProtocol` and Aave reserve state). A keyed Alchemy Free endpoint is sufficient for this lightweight/archive-state role.
- Add `houseedge hypersync-preflight` to verify the Envio token, Base chain id, and archive height before downloading data.
- Record HyperSync URL/chain/archive provenance in acquisition manifest schema v2 without ever storing the API token.
- Keep the old RPC bulk path available only when explicitly configured as `historical_data.event_source: RPC`; Experiment 001 defaults to HyperSync and does not silently fall back.
- Add regression tests that fail if HyperSync-mode acquisition invokes the RPC log-range probe.

The v0.1.7/v0.1.8 Binance timestamp and outcome-blind acquisition fixes remain in force.

## Frozen v0.1.6 design retained

- Freeze Experiment 001 to the Base Uniswap v3 WETH/USDC 5 bp pool at `0xd0b53d9277642d899df5c87a3966a349a798f224`.
- Precommit the calibration window to 2025-07-01..2025-12-31 and the candidate primary window to 2026-01-01..2026-08-31.
- Precommit Hyperliquid ETH perpetual as the hedge venue, 5.0 bp taker+slippage cost, 1-hour funding cadence, 5% NAV delta trigger, and rebalance-to-zero policy.
- Precommit Gate-0 variable friction at 2.5%/yr plus $100/yr fixed cost.
- Change the primary historical fair-value convention to Binance spot ETH/USDC **last trade at or before the Base block timestamp**, max age 3 seconds. No look-ahead is allowed.
- Replace the arbitrary swap-count stationary-bootstrap block with an outcome-blind calibration-derived **daily** dependence length. Calibration and primary inference both operate on UTC-daily P&L increments; the passing calibration report selects the mean block length in days and freeze verifies that exact value.
- Add `houseedge prepare-freeze` to apply only the passing calibration report's selected dates and bootstrap block length to the YAML.
- Historical trade-tape reference inputs may now provide `price` or `last_trade` instead of bid/ask midpoint columns.

All other v0.1.5 governance remains in force: power, regime coverage, same-basis Gate 0, historical protocol fees, JIT diagnostics, Aave Base USDC cash benchmark, statistical/economic/capacity hurdles, VOID rules, micro-live reconciliation, sealed prediction, and post-unblind look counting.

## Install

Python 3.11+ is supported. The project is designed around `uv`.

```bash
uv sync --extra dev
```

HouseEdge automatically loads `.env` from the working/project directory at CLI startup; existing shell environment variables take precedence. Copy `.env.example` to `.env` and fill in your local credentials.

## v0.15 workflow

### 1. Discover the Base WETH/USDC 5 bp pool

```bash
houseedge discover-pool
```

### 2. Acquire all outcome-blind v0.15 data

Bulk historical Base logs now come from Envio HyperSync. Create an Envio API token, keep it local, and use a keyed Base RPC (Alchemy Free is fine) for the small number of state/boundary reads.

```bash
export ENVIO_API_TOKEN="YOUR_ENVIO_API_TOKEN"
export BASE_RPC_URL="https://base-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"

uv run houseedge hypersync-preflight
uv run houseedge discover-pool
uv run houseedge fetch-calibration-data
```

The command prints the absolute output directory before acquisition begins and writes `data/v015_acquisition_status.json` immediately. During the long HyperSync pull it updates that file with `RUNNING` and the latest checkpoint. It reports `FAILED` or `COMPLETE` at termination; a successful return is only possible after all expected artifacts are verified non-empty.

The two raw event artifacts are partitioned Parquet **directories** (their paths still end in `.parquet` for CLI compatibility):

```text
data/raw/calibration_events.parquet/
  part-000...parquet
  part-000...done.json
  ...
  _SUCCESS.json
```

If the process is interrupted during the raw backfill, rerun the same command. Completed chunks are reused automatically.

If the raw event/reference/Aave/funding files are already complete but an older release died at `Loading materialized calibration event dataset for power-noise replay`, **do not redownload them**. v0.2.6 adds a recovery command:

```bash
uv run houseedge derive-calibration-increments
```

It streams `data/raw/calibration_events.parquet/` partition-by-partition, writes `data/calibration/excess_increments.parquet`, rebuilds the outcome-blind acquisition manifest from the existing artifacts, and marks `data/v015_acquisition_status.json` `COMPLETE`.

`fetch-calibration-data` does **not** use your Alchemy endpoint for the multi-month Uniswap/Aave log scan when `historical_data.event_source: HYPERSYNC` (the Experiment 001 default).

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
  data/calibration/excess_increments.parquet \
  data/calibration/eth_reference.parquet \
  data/candidate/eth_reference.parquet \
  data/raw/candidate_events.parquet \
  data/candidate/aave_base_usdc_apy.parquet \
  --output runs/v015_calibration
```

A calibration `PASS` is permission to freeze a test, not evidence that LP edge exists.

### 4. Apply the calibration-selected fields

Only after calibration passes:

```bash
houseedge prepare-freeze \
  --calibration-report runs/v015_calibration/calibration_report.json
```

This writes only the exact candidate-window `start` / `end`, the calibration-derived stationary-bootstrap mean block length **in days**, and `status: READY_TO_FREEZE`. Freeze verifies that all other calibration assumptions still hash to the passing report. Changing the hedge venue, costs, power settings, regime rules, benchmark, reference convention, or capacity hurdle requires a new calibration run.

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

## Eventual primary outcome run

v0.2.0 prepares governance **and acquires the v0.15 real-data inputs**, but **v0.2 still owes exact primary replay-state reconciliation and final real-data cost execution**. The primary runner is intentionally incapable of returning GO unless measurement validity is supplied.

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

Do not hard-code “LPs keep 75%.” v0.2.0 reconstructs the pool’s packed historical `feeProtocol` state and applies the relevant token0/token1 protocol denominator to each swap.

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

### Historical-provider preflight

Experiment 001 defaults to HyperSync for bulk logs:

```bash
uv run houseedge hypersync-preflight
```

`rpc-preflight` is retained for diagnostics or an explicitly configured RPC bulk fallback, but it is no longer part of the normal v0.2.3 acquisition path. A 10-block Alchemy Free `eth_getLogs` limit therefore does not block Experiment 001.
