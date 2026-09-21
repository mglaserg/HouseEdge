# HouseEdge architecture

## Product boundary

HouseEdge is a preregistered market-structure research system. It acquires auditable historical inputs, calibrates a design without opening the primary outcome, replays a hedged AMM LP position, and applies frozen statistical/economic/validity gates.

It is not currently a wallet, transaction broadcaster, automated LP manager, or portfolio allocator. The Streamlit app is a read-only artifact viewer.

## System shape

```text
External sources
  HyperSync | Base RPC | Binance archives | Hyperliquid | Aave
        |
        v
src/houseedge/data/
  provider adapters -> normalized UTC frames -> atomic/checkpointed artifacts
        |
        +---------------- calibration window ----------------+
        |                                                    |
        v                                                    v
streaming calibration replay                         candidate descriptors
daily excess increments                       regime / Gate 0 / JIT / capacity
        |                                                    |
        +------------------ design report -------------------+
                                  |
                         prepare -> seal -> freeze
                                  |
                     replay validation + micro-live evidence
                                  |
                                  v
src/houseedge/experiment.py
  backward alignment -> LP/hedge replay -> cash benchmark -> daily bootstrap
                                  |
                                  v
                         GO | KILL | VOID artifacts
                                  |
                                  v
                         dashboard/ (read-only)
```

The critical architectural seam is between outcome-blind design work and the frozen primary replay. Candidate events may be used to establish dates, coverage, regimes, JIT overlap, Gate 0 inputs, and capacity descriptors; they may not be turned into the exact candidate-primary hedged LP outcome during calibration.

The rationale and enforcement points for this boundary are recorded in [`adr/0001-separate-calibration-from-primary-outcome.md`](adr/0001-separate-calibration-from-primary-outcome.md).

## Package map

```text
src/houseedge/
  amm/
    v3_math.py          concentrated-liquidity price, inventory, and liquidity math
  data/
    acquire.py          v0.15 orchestration, manifests, recovery, reference refresh
    hypersync_base.py   HyperSync client, queries, and Base event decoding
    uniswap_base.py     RPC connection, pool discovery, log/state helpers
    base_rpc.py         block boundaries, resilient range logic, provider preflight
    binance_public.py   public archive cache and sparse last-trade reference
    hyperliquid.py      funding-history adapter
    aave_base.py        on-chain USDC supply-rate history
    reference.py        reference normalization and prospective collection
    storage.py          atomic frame writes, dataset completion, stable hashes
  research/
    alignment.py        backward as-of joins and shift diagnostics
    replay.py           batch and streaming LP/hedge state machines
    benchmark.py        time-matched cash return
    bootstrap.py        dependence length and stationary-bootstrap inference
    power.py            prospective design power
    regime.py           calibration thresholds and candidate coverage
    gate0.py            same-basis fee/LVR/economic screen
    jit.py              short-lived-liquidity diagnostic
    protocol_fee.py     historical feeProtocol state and LP fee fraction
    capacity.py         passive counterfactual capacity sweep
    markouts.py         flow-quality diagnostics and shuffled nulls
    validation.py       GO/KILL/VOID input validity
  calibration.py        outcome-blind v0.15 design gate orchestration
  experiment.py         frozen primary replay and decision artifacts
  prereg.py             prepare/freeze/seal/look registries
  config.py             YAML loading and canonical/calibration hashes
  cli.py                thin Typer command surface
  demo.py               isolated synthetic data path

configs/                machine-readable experiment and demo specifications
prereg/                 human/machine research contract and prediction template
scripts/                narrow operational recovery/diagnostic tools
tests/                  unit and regression coverage
dashboard/              read-only Streamlit artifact browser
docs/                   architecture, development, and authoritative sources
```

## Experiment state machine

```text
CALIBRATION_REQUIRED
        |
        | calibrate-design == PASS
        v
prepare-freeze writes only selected dates/block length
        |
        v
READY_TO_FREEZE -- prediction sealed --> freeze registry entry
        |
        | replay + micro-live validity evidence
        v
primary preflight VALID
        |
        | register outcome look immediately before replay
        v
GO | KILL | VOID
```

`calibration_basis_hash` normalizes the fields calibration is allowed to select, then binds every other design assumption. Freeze checks the report, selected fields, prediction seal, and hash identity.

## Data contracts

### Event datasets

Large Base histories use a directory whose name ends in `.parquet`:

```text
data/raw/candidate_events.parquet/
  part-<from>-<to>.parquet
  part-<from>-<to>.done.json
  _SUCCESS.json
```

Parts contain normalized `Swap`, `Mint`, `Burn`, and `SetFeeProtocol` rows. Required replay ordering is deterministic by UTC `timestamp`, `block_number`, and `log_index`. Protocol-fee state is attached before downstream fee accounting.

### Reference data

Reference frames normalize an observation time and a `mid` field even when the configured semantic is last trade. Eligibility flags keep backward-alignment observations separate from lower-frequency regime samples. Primary joins use the latest eligible observation at or before the Base event time and reject observations older than the configured limit.

### Funding and benchmark data

Funding rows carry UTC timestamps and per-interval funding rates; real primary replay cannot use an annualized fallback. Benchmark rows carry UTC timestamps and Aave supply APY; returns are integrated over the exact replay window.

### Provenance

The acquisition manifest binds source settings, windows, block ranges, config identity, output hashes, and an explicit `candidate_primary_pnl_opened: false` assertion. API tokens are process inputs and never provenance fields.

### Numeric storage

EVM values can exceed native signed int64. `storage.parquet_safe_frame` serializes affected integer columns as decimal strings without loss. Mathematical consumers must convert explicitly; storage must never silently coerce them through float.

## Runtime flows

### Acquisition

1. Resolve calibration and candidate UTC windows to Base block boundaries via RPC.
2. Fetch bounded HyperSync chunks.
3. Seed and attach historical protocol-fee state.
4. Write each completed part and checkpoint immediately.
5. Build sparse Binance references at swap targets plus regime samples.
6. Acquire Aave rates and Hyperliquid funding.
7. Replay the calibration window only to derive daily excess increments.
8. Verify every output and write the manifest/status file.

Interrupted event acquisition resumes from part checkpoints. A dataset-level success marker is written only after all planned ranges complete.

### Design calibration

1. Estimate dependence from calibration-window daily excess increments.
2. Evaluate power at the registered alternatives.
3. Stream candidate parts to establish aligned dates and descriptors.
4. Evaluate regime coverage, same-basis Gate 0, JIT, and passive capacity.
5. Write a report containing both canonical config hash and calibration-basis hash.

No exact candidate-primary hedged return is a calibration output.

### Primary experiment

1. Assert the spec is frozen.
2. Load external replay-validation and micro-live reports.
3. Run outcome-blind validity preflight.
4. If preflight is valid, append an outcome-look record.
5. Align references, compute diagnostics, replay LP/hedge state, apply funding and benchmark.
6. Aggregate to UTC-daily P&L, bootstrap with the frozen dependence length, and apply all gates.
7. Write immutable run artifacts and summary.

## Core invariants

- No future reference observation may enter an event row.
- Acquisition/calibration cannot reveal candidate-primary exact LP profitability.
- Primary economics use actual historical funding and the time-matched benchmark.
- Statistical and primary bootstrap units are UTC days, not swaps.
- Protocol-fee history is reconstructed; no permanent “LPs keep 75%” constant is allowed.
- Boundary-cross fee treatment, hedge rules, costs, and ranges come from the registered config.
- All three GO gates must pass, and validity must not be `VOID`.
- Outcome-look accounting happens before primary replay after validity preflight.
- Large histories stay bounded-memory in acquisition and calibration.
- Synthetic results are isolated and labeled.

## Failure model

- Transport failures retry the affected bounded chunk rather than restart the full window.
- Partial acquisition leaves checkpoints and a status diagnostic.
- Atomic file writes use a temporary sibling plus replace.
- Missing/empty artifacts prevent successful acquisition finalization.
- A failed research gate produces `FAIL` or `KILL`; code must not tune around it.
- Missing measurement evidence produces `VOID` or blocks primary access.

## Extension rules

- Add a provider under `data/`, normalize it there, and keep its SDK/schema out of research modules.
- Add a diagnostic under `research/` and label whether it affects design, validity, or the primary decision.
- Add a new economic variant as a new experiment/config rather than an `if` branch that weakens Experiment 001.
- Keep CLI handlers thin and reusable logic importable/testable.
- Prefer Parquet plus explicit manifests over introducing a database until measured workload requires one.
- Record durable boundary changes in this document and, when choices need history or trade-off context, add an ADR under `docs/adr/`.
