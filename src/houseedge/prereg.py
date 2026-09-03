from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone
from houseedge.config import canonical_hash, load_yaml


def freeze_record(config_path: str | Path, registry_path: str | Path = "data/prereg_registry.jsonl") -> dict:
    cfg=load_yaml(config_path)
    rec={
        "experiment_id": cfg["experiment_id"],
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "spec_sha256": canonical_hash(cfg),
        "primary_trial_count": int(cfg["inference"]["primary_trial_count"]),
        "status": cfg.get("status","UNKNOWN"),
    }
    p=Path(registry_path); p.parent.mkdir(parents=True,exist_ok=True)
    existing=[]
    if p.exists():
        existing=[json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        prior=[x for x in existing if x.get("experiment_id")==rec["experiment_id"]]
        if prior:
            if prior[-1]["spec_sha256"] != rec["spec_sha256"]:
                raise RuntimeError("Experiment ID already registered with a different spec hash. Create a new experiment/variant ID instead of overwriting.")
            return prior[-1]
    with p.open("a",encoding="utf-8") as f:
        f.write(json.dumps(rec,sort_keys=True)+"\n")
    return rec


def assert_frozen(config_path: str | Path, registry_path: str | Path = "data/prereg_registry.jsonl") -> None:
    cfg=load_yaml(config_path); h=canonical_hash(cfg); exp=cfg["experiment_id"]
    p=Path(registry_path)
    if not p.exists():
        raise RuntimeError("No local preregistration record. Run `houseedge freeze` before the real experiment.")
    rows=[json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    match=[x for x in rows if x.get("experiment_id")==exp]
    if not match:
        raise RuntimeError(f"No preregistration record for {exp}")
    if match[-1]["spec_sha256"] != h:
        raise RuntimeError("Current config hash differs from frozen preregistration. Do not run under the same experiment ID.")
