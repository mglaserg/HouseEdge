from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json
import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def canonical_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PoolSpec:
    token0_symbol: str
    token0_address: str
    token0_decimals: int
    token1_symbol: str
    token1_address: str
    token1_decimals: int
    fee_tier_pips: int
    lp_share_of_swap_fee: float
    pool_address: str | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "PoolSpec":
        p = cfg["pool"]
        return cls(**{k: p[k] for k in cls.__dataclass_fields__ if k in p})
