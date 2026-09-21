from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def canonical_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def reference_policy_hash(config: dict[str, Any]) -> str | None:
    """Hash the complete selected fair-value policy used by alignment.

    The reference-feasibility report path/hash is provenance rather than a
    policy input, so it is excluded. Venue order, symbols, policy method,
    freshness grid, selected freshness, and alignment semantics remain bound.
    """
    sample = config.get("sample", {})
    policy = sample.get("reference_policy")
    if policy is None:
        return None
    policy = deepcopy(policy)
    policy.pop("selection_report_sha256", None)
    payload = {
        "primary_reference": sample.get("primary_reference"),
        "reference_policy": policy,
        "primary_alignment": sample.get("primary_alignment", {}),
        "max_missing_reference_fraction": config.get("validity", {}).get(
            "max_missing_reference_fraction"
        ),
    }
    return canonical_hash(payload)


def assert_reference_policy_selected(config: dict[str, Any]) -> None:
    policy = config.get("sample", {}).get("reference_policy")
    if policy is None:
        return
    if policy.get("selection_status") != "SELECTED_ON_CALIBRATION":
        raise RuntimeError(
            "Reference policy has not been selected on the calibration window. "
            "Run `houseedge rebuild-references` before design calibration."
        )
    selected = policy.get("selected_max_age_seconds")
    configured = config.get("sample", {}).get("primary_alignment", {}).get(
        "max_age_seconds"
    )
    if selected is None or configured is None or abs(float(selected) - float(configured)) > 1e-12:
        raise RuntimeError(
            "Selected reference freshness does not match sample.primary_alignment.max_age_seconds."
        )


def with_reference_policy_selection(
    config: dict[str, Any],
    *,
    policy_name: str,
    max_age_seconds: float,
) -> dict[str, Any]:
    selected = deepcopy(config)
    sample = selected.setdefault("sample", {})
    policy = sample.get("reference_policy")
    if policy is None:
        raise RuntimeError("Config has no sample.reference_policy to select")
    policy["selection_status"] = "SELECTED_ON_CALIBRATION"
    policy["selected_policy"] = str(policy_name)
    policy["selected_max_age_seconds"] = float(max_age_seconds)
    sample.setdefault("primary_alignment", {})["max_age_seconds"] = float(max_age_seconds)
    assert_reference_policy_selected(selected)
    return selected


def calibration_basis_hash(config: dict[str, Any]) -> str:
    """Hash assumptions that must not change after v0.15 calibration.

    The outcome-blind calibration is allowed to select the primary start/end
    and then move status to READY_TO_FREEZE. Everything else that affects the
    design remains bound to the calibration report.
    """
    cfg=deepcopy(config)
    cfg["status"]="CALIBRATION_REQUIRED"
    cfg["registered_at"]=None
    if "sample" in cfg:
        cfg["sample"]["start"]=None
        cfg["sample"]["end"]=None
        # The report digest is provenance written after the policy is selected;
        # it is not a research-design input and cannot recursively bind itself.
        policy=cfg["sample"].get("reference_policy")
        if policy is not None:
            policy.pop("selection_report_sha256",None)
    # v0.1.8 retains the v0.1.6 rule allowing one post-calibration edit: the inference block length must
    # be filled with the exact outcome-blind value selected by calibration.
    if "inference" in cfg:
        cfg["inference"]["stationary_bootstrap_mean_block_days"]=None
    return canonical_hash(cfg)


@dataclass(frozen=True)
class PoolSpec:
    token0_symbol: str
    token0_address: str
    token0_decimals: int
    token1_symbol: str
    token1_address: str
    token1_decimals: int
    fee_tier_pips: int
    pool_address: str | None = None
    lp_share_of_swap_fee: float = 1.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "PoolSpec":
        p = cfg["pool"]
        return cls(**{k: p[k] for k in cls.__dataclass_fields__ if k in p})
