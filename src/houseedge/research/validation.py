from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ValidityResult:
    status: str
    failures: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate_void_criteria(
    *,
    missing_reference_fraction: float,
    max_missing_reference_fraction: float,
    funding_gap_hours: float,
    max_funding_gap_hours: float,
    protocol_fee_history_complete: bool,
    replay_state_valid: bool,
    micro_live_fee_error_bps_nav: float | None,
    max_micro_live_fee_error_bps_nav: float,
) -> ValidityResult:
    failures: list[str] = []
    if missing_reference_fraction > max_missing_reference_fraction:
        failures.append("REFERENCE_COVERAGE")
    if funding_gap_hours > max_funding_gap_hours:
        failures.append("FUNDING_COVERAGE")
    if not protocol_fee_history_complete:
        failures.append("PROTOCOL_FEE_HISTORY")
    if not replay_state_valid:
        failures.append("REPLAY_STATE_RECONCILIATION")
    if micro_live_fee_error_bps_nav is not None and abs(micro_live_fee_error_bps_nav) > max_micro_live_fee_error_bps_nav:
        failures.append("MICRO_LIVE_FEE_RECONCILIATION")
    return ValidityResult("VOID" if failures else "VALID", tuple(failures))
