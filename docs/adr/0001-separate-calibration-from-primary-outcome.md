# ADR 0001: Separate calibration from the primary outcome

**Status:** Accepted  
**Date:** 2026-09-21  
**Decision owners:** HouseEdge research project

## Context

Experiment 001 needs calibration-period information to estimate noise, dependence, power, and regime thresholds. It also needs candidate-window information to establish coverage, sample duration, regime representation, JIT overlap, and passive capacity. Using the candidate window to tune or preview the exact hedged LP result would contaminate the single registered primary test.

The same event dataset can technically support both design diagnostics and primary replay, so file-level access control alone does not define the boundary. The boundary must be semantic and enforced in code, artifacts, hashes, tests, and operator workflow.

## Decision

HouseEdge maintains two distinct computation paths:

1. Outcome-blind calibration may replay the separate calibration window and may inspect only preregistered candidate descriptors that do not reveal exact candidate-primary hedged LP profitability.
2. Primary replay may run only after a passing calibration, permitted config transition, sealed prediction, frozen spec, and passing replay/micro-live validity preflight.

Candidate-window calibration outputs may include aligned dates/counts, realized-variance regimes, Gate 0 inputs, JIT diagnostics, and passive-capacity estimates. They must not include the exact candidate-primary hedged return, primary confidence interval, or implied `GO`/`KILL` result.

`calibration_basis_hash` binds assumptions that calibration is not allowed to change. The only selected fields applied by `prepare-freeze` are the candidate sample bounds and calibration-derived stationary-bootstrap mean block length. An outcome look is appended immediately before primary replay, after validity preflight succeeds.

## Consequences

- Calibration `PASS` means the experiment is sufficiently designed to freeze; it is not evidence that LP edge exists.
- Candidate event data is not generally secret, but functions operating on it must have a documented output role.
- Recovery and reference-repair tools may operate on candidate timestamps while explicitly preserving `candidate_primary_pnl_opened: false`.
- Refactors that merge calibration and primary orchestration are not allowed merely to reduce duplication.
- Any new candidate diagnostic must be classified before implementation. If it can reveal or tune the primary outcome, it belongs in a new registered look or experiment.
- Bugs discovered after unblinding cannot restore the original look; a rerun is a new EdgeLab look.

## Alternatives considered

### Use the candidate outcome during design and rely on researcher discretion

Rejected because discretionary exposure creates an unverifiable garden of forking paths and makes the single-trial claim meaningless.

### Use only calibration-window data for every design check

Rejected because prospective power/dependence belongs exclusively to calibration, but candidate duration, reference coverage, and regime representation must be verified for the actual intended window without calculating its exact LP outcome.

### Encrypt or physically seal all candidate data until freeze

Not adopted as the primary mechanism because acquisition integrity and outcome-blind candidate descriptors are needed before freeze. Semantic separation plus manifests, hashes, and explicit commands is the enforceable project boundary.

## Verification

- `src/houseedge/data/acquire.py` records `candidate_primary_pnl_opened: false`.
- `src/houseedge/calibration.py` emits design-gate outputs and no exact primary hedged LP result.
- `src/houseedge/prereg.py` validates report status, basis hash, selected fields, and prediction seal.
- `src/houseedge/cli.py` separates `calibrate-design` from guarded `run` and registers an outcome look before primary replay.
- Tests cover outcome-blind acquisition, calibration separation, freeze transitions, and look accounting.
