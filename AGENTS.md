# HouseEdge agent guide

This file is the operating contract for coding agents working in this repository.

## Read this first

Before making a meaningful change, read these files in order:

1. `PROJECT_STATUS.md` — what is true now, what is blocked, and the immediate objective.
2. `ROADMAP.md` — capability sequence and promotion gates.
3. `docs/ARCHITECTURE.md` — system boundaries, data flow, and invariants.
4. `prereg/experiment_001.md` and `configs/experiment_001.yaml` for work that can affect Experiment 001.
5. `CHANGELOG.md` — recent implementation history.
6. Relevant records under `docs/adr/` — durable decisions and their trade-offs.
7. `docs/SOURCES.md` — authoritative protocol and provider references.

Repository state is the durable source of truth. Do not substitute chat history or an ignored local artifact for checked-in project memory.

## Mission

HouseEdge tests whether supplying AMM liquidity earns a durable, capacity-aware premium after adverse selection, hedging, funding, protocol fees, operating costs, and a time-matched cash benchmark.

The governing sequence is:

```text
Counterparty -> Compensation -> Costs -> Falsifier -> EdgeLab -> Build
```

A `KILL` is a valid research result. A measurement failure is `VOID`, not evidence against the hypothesis. A favorable exploratory diagnostic is never permission to weaken a preregistered gate.

## Non-negotiable research boundaries

- Keep calibration and candidate-primary outcomes separate. Outcome-blind acquisition and design calibration must not calculate, log, summarize, or inspect candidate-primary hedged LP P&L.
- Never use future reference information. Primary reference alignment is backward-only and bounded by the configured staleness limit.
- Do not change a design input after looking at the primary outcome. New ranges, hedge bands, venues, pools, references, or decision rules require a new registered experiment unless the preregistration explicitly permits the change.
- Do not run the primary outcome casually. `houseedge run` spends an outcome look after preflight succeeds; every post-unblind rerun is a new look.
- Preserve the distinction between `GO`, `KILL`, and `VOID`.
- Markouts, alignment shifts, JIT estimates, and passive capacity sweeps are diagnostics unless preregistered otherwise.
- Range optimization cannot rescue a primary `KILL`.
- Keep synthetic/demo results visibly synthetic. They are plumbing checks, never evidence of edge.
- Do not add wallet signing, private keys, transaction broadcasting, or live execution to this research repository without an explicit architectural decision and user request.

## Architecture boundaries

- `src/houseedge/data/` owns provider access, normalization, checkpointed acquisition, and artifact storage.
- `src/houseedge/amm/` owns protocol math that is independent of the research decision.
- `src/houseedge/research/` owns alignment, replay, benchmarks, inference, diagnostics, and validation.
- `src/houseedge/calibration.py` may use calibration outcomes and outcome-blind candidate descriptors, but not candidate-primary LP profitability.
- `src/houseedge/experiment.py` owns the frozen primary decision path.
- `src/houseedge/prereg.py` owns sealing, freeze validation, and outcome-look accounting.
- `src/houseedge/cli.py` is orchestration only; do not bury research logic in command handlers.
- `dashboard/` is read-only presentation. It must not mutate research inputs, freeze state, or registries.

Provider-specific code should stop at the data boundary. Research modules should consume normalized frames rather than call HyperSync, RPC, Binance, Hyperliquid, or Aave directly.

## Data and storage rules

- Store timestamps as UTC and make join direction explicit.
- Preserve EVM integers losslessly. Values wider than signed int64 are decimal strings at the Parquet boundary and converted explicitly at use sites.
- Treat raw downloads and completed Parquet parts as immutable inputs. Rebuild derived artifacts rather than editing source rows in place.
- Large event histories remain partitioned and streamable. Do not reintroduce whole-window materialization into acquisition or calibration.
- A partitioned dataset is complete only when its `_SUCCESS.json` exists and its checkpoints/artifacts are non-empty.
- Manifests must retain source, window, configuration hash, artifact hash, and outcome-blind provenance. Never write API tokens or RPC credentials into them.
- Keep generated `data/` and `runs/` artifacts out of Git except for intentional fixtures or `.gitkeep` files.

## How to choose work

Unless the user explicitly changes priority:

1. Take the highest-priority unblocked item in `PROJECT_STATUS.md` and `ROADMAP.md`.
2. Prefer one complete, testable research slice over several partial features.
3. Preserve falsification-first sequencing: cheap validity and power checks before infrastructure, optimization, or live work.
4. Resolve specification inconsistencies before freeze; do not guess which conflicting research assumption should win.

If a requested change conflicts with the preregistration or a durable architecture rule, call out the conflict. Do not silently route around it.

## Definition of done

A meaningful change should include, where applicable:

- implementation and focused regression tests;
- no-lookahead and outcome-blindness tests for research-path changes;
- bounded-memory coverage for large-data changes;
- clear failure, resume, and partial-artifact behavior;
- CLI/help and artifact-schema updates;
- documentation and project-memory updates;
- commands actually run and their honest results.

Research changes additionally need an explicit mechanism, falsifier, data identity, cost treatment, decision impact, and classification as primary, calibration, diagnostic, or synthetic.

## Required project-memory updates

For meaningful code or research changes, update the relevant repository memory in the same change:

- `PROJECT_STATUS.md` when current/next/blocked state changes;
- `ROADMAP.md` when milestone status, scope, or ordering changes;
- `CHANGELOG.md` with a concise `Unreleased` entry;
- `docs/ARCHITECTURE.md` when a durable boundary, data flow, or invariant changes;
- preregistration/config files only through their governed transition, never as routine documentation cleanup.

Tiny wording or formatting fixes do not require every file.

## Verification

Default development checks:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Useful narrower checks:

```bash
uv run pytest tests/test_alignment.py tests/test_prereg.py tests/test_validation.py
uv run pytest tests/test_chunked_acquisition.py tests/test_streaming_replay.py tests/test_streaming_calibration.py
uv run houseedge demo
```

Commands that contact providers, download multi-month history, freeze a specification, seal a prediction, or open a primary outcome are not routine verification. Run them only when the task calls for them and prerequisites are understood.

Never claim a check passed unless it was run. If the local environment is broken or dependencies are missing, report that separately from code failures.

## Repository hygiene

- Keep secrets in environment variables or an ignored `.env`; never commit `.env`.
- Preserve unrelated working-tree changes.
- Prefer small modules and explicit functions over framework-heavy abstractions.
- Add dependencies only when the workload justifies them.
- Use authoritative sources for protocol semantics and update `docs/SOURCES.md` when a new source becomes normative.
- Do not commit real research outputs merely to make a status claim reproducible; record hashes and the verification command instead.

## Handoff standard

Before handing off meaningful work, leave `PROJECT_STATUS.md` accurate enough that a fresh agent can answer:

- What works now?
- What remains synthetic, outcome-blind, or unverified?
- What was most recently checked?
- What is the next gated action?
- What would spend an outcome look or alter the research design?
- Which files should be touched next?

If those answers are not obvious, the handoff is incomplete.
