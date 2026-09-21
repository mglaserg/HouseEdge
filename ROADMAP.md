# HouseEdge roadmap

This root file is the **canonical roadmap**. Milestones are research-capability gates, not version-number promises.

Status vocabulary:

- **DONE** — implemented for the stated scope.
- **ACTIVE** — current highest-priority milestone.
- **QUEUED** — planned after prerequisites pass.
- **BLOCKED** — cannot advance without a named prerequisite or decision.
- **PARKED** — intentionally deferred.

## M0 — Experiment contract and research core — DONE

- counterparty, mechanism, falsifier, and decision rule defined;
- machine-readable Experiment 001 specification;
- backward-only alignment and no-lookahead tests;
- concentrated-liquidity math and discrete hedge replay;
- protocol-fee, funding, benchmark, bootstrap, capacity, and validity components;
- prediction seal, freeze registry, and outcome-look registry;
- synthetic end-to-end demo isolated from the real experiment.

**Gate passed:** HouseEdge can express and test the registered mechanism without relying on a directional-price forecast.

## M1 — Outcome-blind historical data plane — DONE

- HyperSync as the default bulk Base event source;
- RPC limited to block boundaries and sparse historical state reads;
- bounded-memory, resumable partitioned event acquisition;
- Binance trade-tape reference construction;
- Aave Base USDC benchmark and Hyperliquid funding inputs;
- artifact manifests, hashes, checkpoints, and explicit outcome-blind provenance;
- streaming recovery of calibration increments from completed downloads;
- targeted reference repair tooling without candidate-primary P&L access.

**Gate passed in code:** acquisition can produce all v0.15 inputs without opening the candidate-primary outcome. Real local artifact completeness remains an operational check, not a repository guarantee.

## M2 — Audited v0.15 design calibration — ACTIVE

### Scope

- acquire or restore the v0.15 artifact tree — **BLOCKED in this checkout: no artifacts or provider credentials**;
- verify calibration/candidate artifact completeness and source provenance;
- verify actual backward merge coverage at the configured staleness limit;
- resolve ETHUSDT/ETHUSDC naming and last-trade/midpoint specification drift — **DONE**;
- run prospective power on separate calibration daily excess increments;
- select the dependence block length from calibration only;
- run candidate-window regime, Gate 0, JIT, and passive-capacity diagnostics without primary replay;
- produce a reproducible calibration report whose basis hash matches the config;
- classify the design `PASS` or `FAIL` without treating `PASS` as evidence of edge.
- restore a green test baseline for reference naming, timestamp-unit portability, and cross-platform CLI output assertions — **DONE (50 passed)**.

### Gate

A complete report has matching provenance/configuration, all required design gates are evaluated, candidate-primary LP P&L remains unopened, and the report's status is accepted without post hoc rule changes.

If this gate fails, redesign must become a newly documented experiment iteration rather than an invisible edit.

## M3 — Freeze-ready Experiment 001 — QUEUED

Prerequisite: M2 `PASS`.

- apply only the calibration-selected candidate dates and bootstrap block length;
- transition the config to `READY_TO_FREEZE`;
- fill and seal the prediction template;
- verify config, calibration-basis, prediction, and registry hashes;
- freeze the primary specification;
- publish a compact runbook identifying the exact inputs and preflight evidence required for the one primary look.

### Gate

`houseedge freeze` succeeds without changing any non-permitted assumption, and a fresh operator can verify the frozen identity before outcome access.

## M4 — Replay reconciliation and micro-live telemetry — QUEUED

Prerequisite: M3.

- reconcile historical replay state against independently derived pool/position state;
- define the smallest viable permissionless telemetry pilot selected from the calibration result;
- collect on-chain accrued-fee observations without adding general execution capability to the research engine;
- compare replayed and observed fees within the preregistered 1 bp NAV tolerance;
- emit machine-readable replay-validation and micro-live reports consumed by primary preflight;
- document custody, key, and operational boundaries before any live transaction tooling exists.

### Gate

Both validity reports pass and are reproducible. Failure is `VOID`/blocked measurement, not `KILL`.

## M5 — Single primary outcome — QUEUED

Prerequisites: M3 and M4.

- run outcome-blind preflight before registering a look;
- open the primary outcome once;
- compute daily stationary-bootstrap inference with the frozen block length;
- apply statistical, economic, and passive-capacity gates exactly as frozen;
- publish `GO`, `KILL`, or `VOID` with artifact/config hashes;
- preserve every later rerun as a new EdgeLab look.

### Gate

The result is reproducible from frozen inputs and registries, with no unregistered variants influencing the primary decision.

## M6 — Productize only validated research — BLOCKED

Prerequisite: an Experiment 001 result plus an explicit follow-on decision.

Possible directions:

- if `GO`, design a separately governed execution/portfolio handoff rather than embedding unrestricted execution here;
- if `KILL`, archive the experiment as a successful falsification and register materially different variants as new trials;
- if `VOID`, fix measurement and register the next look without relabeling it as the original primary;
- promote the dashboard into a provenance-first experiment browser only after artifacts and state transitions are stable.

## Parked ideas

These should not distract from M2–M5 without explicit reprioritization:

- optimizing ranges or hedge bands on the candidate sample;
- additional pools, chains, fee tiers, or hedge venues;
- active/JIT liquidity strategies;
- routing or transaction execution;
- portfolio allocation across HouseEdge sleeves;
- distributed infrastructure, databases, or orchestration not justified by measured workload.
