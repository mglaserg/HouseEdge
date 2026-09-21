# Architecture decision records

Architecture decision records (ADRs) preserve the reason behind durable choices that are easy to lose in code review or chat history.

Create an ADR when a change affects one or more of:

- calibration/primary outcome separation;
- preregistration or outcome-look semantics;
- provider trust boundaries or canonical data sources;
- normalized data contracts or persistent artifact formats;
- replay/inference units or decision rules;
- security or execution scope;
- a dependency or service that would be expensive to reverse.

Do not create an ADR for routine implementation details, refactors that preserve behavior, or temporary debugging choices.

## Naming

Use the next four-digit number and a short kebab-case title:

```text
0002-short-decision-title.md
```

## Template

```markdown
# ADR NNNN: Decision title

**Status:** Proposed | Accepted | Superseded  
**Date:** YYYY-MM-DD  
**Decision owners:** project/research owner

## Context

What problem or constraint requires a durable decision?

## Decision

What will the project do?

## Consequences

What becomes easier, harder, required, or explicitly out of scope?

## Alternatives considered

What credible alternatives were rejected, and why?

## Verification

How can a contributor tell the decision is still enforced?
```

When an ADR changes, prefer a new ADR that supersedes it instead of rewriting the original rationale. Update `docs/ARCHITECTURE.md`, `PROJECT_STATUS.md`, and `ROADMAP.md` as needed so the current state remains easy to find.
