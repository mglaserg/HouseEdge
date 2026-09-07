from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from copy import deepcopy
import hashlib
import json
import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def canonical_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


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
    # v0.1.6 allows one post-calibration edit: the inference block length must
    # be filled with the exact outcome-blind value selected by calibration.
    if "inference" in cfg:
        cfg["inference"]["stationary_bootstrap_mean_block_swaps"]=None
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
