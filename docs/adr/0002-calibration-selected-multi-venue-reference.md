# ADR 0002: Calibration-selected multi-venue reference

**Status:** Accepted  
**Date:** 2026-09-21

## Context

Experiment 001 originally depended on one Binance spot ETHUSDT archive and a fixed three-second age. Missing archive coverage could make an otherwise measurable candidate window invalid. The primary LP outcome is still unopened, so reference feasibility can be amended only through an explicit outcome-blind design transition.

## Decision

Use a deterministic priority fallback: Binance spot ETHUSDT last trade first, then Bybit spot ETHUSDT last trade. Every eligible observation must be at or before the Base event timestamp.

Select the maximum age using the calibration window only. Test the fixed grid `[1, 2, 3, 5, 10]` seconds and choose the smallest age whose swap-weighted missing fraction is at most 0.5%. Freeze the venue order and selected age. Apply that frozen policy to the candidate window solely as an out-of-sample coverage validity check; candidate-primary LP P&L is never opened and candidate coverage cannot tune the rule.

Bind the complete selected policy into a dedicated policy hash and the calibration-basis hash. Keep the feasibility-report digest as provenance outside the basis hash to avoid recursive identity.

## Consequences

- Reference feasibility is less dependent on one venue while remaining deterministic.
- A candidate missing fraction above 0.5% is a failed validity check, not permission to widen freshness or reorder venues.
- Existing Base/HyperSync event parts are reused. Only public CEX archives may be fetched by the reference rebuild.
- Calibration increments must be regenerated after the selected age is written to config.
- A future median, new venue, new grid, or different threshold requires another governed experiment amendment.
