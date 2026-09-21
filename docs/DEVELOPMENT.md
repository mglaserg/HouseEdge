# Development guide

## Setup

HouseEdge supports Python 3.11+ and uses `uv` for its reproducible environment.

```bash
uv sync --extra dev
```

Copy `.env.example` to an ignored `.env` when provider-backed commands are needed. The CLI loads it automatically and existing shell variables take precedence.

Typical credentials are:

- `ENVIO_API_TOKEN` for HyperSync bulk history;
- `BASE_RPC_URL` for Base block boundaries and sparse historical state reads.

Never put secrets in config, manifests, fixtures, logs, or screenshots.

## Fast feedback

Run the full local baseline:

```bash
uv run pytest
uv run ruff check .
```

Run focused suites while iterating:

```bash
uv run pytest tests/test_alignment.py tests/test_prereg.py tests/test_validation.py
uv run pytest tests/test_chunked_acquisition.py tests/test_streaming_replay.py tests/test_streaming_calibration.py
```

Validate end-to-end plumbing without touching Experiment 001:

```bash
uv run houseedge demo
```

The synthetic demo may write under `runs/demo`; it does not freeze the spec, seal a prediction, register a primary look, or use real candidate outcomes.

## Command risk classes

### Routine and local

- unit tests and Ruff;
- `houseedge demo`;
- read-only inspection of checked-in config/docs;
- diagnostics against copied/fixture artifacts.

### Provider-backed or long-running

- `houseedge hypersync-preflight`;
- `houseedge discover-pool`;
- `houseedge fetch-calibration-data`;
- `scripts/refresh_reference.py`;
- `scripts/repair_candidate_reference.py`.

These may contact external services or download large archives. Confirm output roots and reuse checkpoints/caches.

### Governed state transitions

- `houseedge prepare-freeze`;
- `houseedge seal-prediction`;
- `houseedge freeze`;
- `houseedge run`.

Read `AGENTS.md`, `PROJECT_STATUS.md`, the preregistration, and the relevant command implementation before using these. `houseedge run` can register/spend an outcome look after preflight; it is never a smoke test.

## Coding conventions

- Keep provider and wire-format logic in `src/houseedge/data/`.
- Keep mathematical/statistical logic in small functions under `amm/` or `research/`.
- Use UTC-aware pandas timestamps at boundaries.
- Make as-of direction and staleness explicit.
- Prefer deterministic ordering and seeded simulations in tests.
- Preserve arbitrary-precision EVM integers until an explicit conversion point.
- Use `write_frame` for atomic derived artifacts and storage normalization.
- For multi-month data, design and test a streaming/partitioned path.
- Keep the CLI as orchestration; test reusable functions directly.

The current codebase is compact and does not enforce an autoformatter. Ruff is the intended lint baseline; avoid unrelated mass-formatting in feature changes.

## Test expectations by change type

| Change | Minimum focused coverage |
| --- | --- |
| Reference/alignment | exact timestamp, stale row, backward-only/no future row, timestamp-unit portability |
| Acquisition | chunk boundaries, retry/resume, partial artifact, completion marker, manifest provenance |
| Storage | round trip, atomic failure behavior, wide integers, file and partitioned dataset |
| Replay | batch/stream equivalence, chunk-boundary state, funding intervals, final hedge close |
| Calibration | no candidate-primary P&L, daily aggregation, bounded-memory path, basis hash |
| Preregistration | invalid transition rejection, hash mismatch, prediction seal, look accounting |
| Decision/validity | each `VOID` criterion and all-of-three GO rule |

## Working with real artifacts

`data/raw/`, `data/calibration/`, `data/candidate/`, `data/cache/`, and `runs/` are ignored because they may be large and machine-specific. Their absence from Git does not imply acquisition has not run; their presence locally does not make a claim reproducible.

When reporting a real run, record:

- the exact command;
- config and calibration-basis hashes;
- input/output artifact hashes;
- source endpoints and windows without credentials;
- whether candidate-primary P&L was opened;
- the outcome-look number, if any;
- relevant environment/package versions.

Do not commit a real outcome merely to share it. Deliberately choose an appropriate artifact channel after the governance state permits disclosure.

## Documentation workflow

For a meaningful change:

1. update code and tests;
2. run the checks that are available;
3. add a concise `CHANGELOG.md` entry;
4. update `PROJECT_STATUS.md` when current state changed;
5. update `ROADMAP.md` when a milestone changed;
6. update `docs/ARCHITECTURE.md` when a durable boundary or invariant changed.

Keep the README focused on installation and operator workflow. Put current truth in `PROJECT_STATUS.md`, future sequencing in `ROADMAP.md`, and stable design in `docs/ARCHITECTURE.md`.
