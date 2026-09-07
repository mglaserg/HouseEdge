from __future__ import annotations
from pathlib import Path
import hashlib
import json
import yaml
from datetime import datetime, timezone
from houseedge.config import canonical_hash, calibration_basis_hash, load_yaml


def file_sha256(path: str | Path) -> str:
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def seal_prediction(prediction_path: str | Path, registry_path: str | Path = "data/prediction_registry.jsonl") -> dict:
    p=Path(prediction_path)
    if not p.exists():
        raise FileNotFoundError(p)
    rec={
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "prediction_path": str(p),
        "prediction_sha256": file_sha256(p),
    }
    r=Path(registry_path); r.parent.mkdir(parents=True,exist_ok=True)
    with r.open("a",encoding="utf-8") as f:
        f.write(json.dumps(rec,sort_keys=True)+"\n")
    return rec


def _load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))



def apply_calibration_selection(
    config_path: str | Path,
    calibration_report_path: str | Path,
) -> dict:
    """Apply only the outcome-blind fields selected by a passing calibration.

    The calibration-basis hash intentionally normalizes these fields, so this
    transition cannot alter the assumptions that generated the PASS.
    """
    cfg=load_yaml(config_path)
    report=_load_json(calibration_report_path)
    if report.get("status") != "PASS":
        raise RuntimeError("Calibration report did not PASS; cannot prepare the spec for freeze.")
    if report.get("calibration_basis_sha256") != calibration_basis_hash(cfg):
        raise RuntimeError("Current design assumptions differ from the calibration report.")
    candidate=report.get("candidate_window",{})
    block=report.get("bootstrap",{}).get("selected_mean_block_swaps")
    if not candidate.get("start") or not candidate.get("end") or block is None:
        raise RuntimeError("Calibration report is missing candidate dates or selected bootstrap block length.")
    cfg["sample"]["start"]=candidate["start"]
    cfg["sample"]["end"]=candidate["end"]
    cfg["inference"]["stationary_bootstrap_mean_block_swaps"]=float(block)
    cfg["status"]="READY_TO_FREEZE"
    Path(config_path).write_text(yaml.safe_dump(cfg,sort_keys=False),encoding="utf-8")
    return {
        "status":cfg["status"],
        "sample_start":cfg["sample"]["start"],
        "sample_end":cfg["sample"]["end"],
        "stationary_bootstrap_mean_block_swaps":float(block),
        "calibration_basis_sha256":calibration_basis_hash(cfg),
    }


def freeze_record(
    config_path: str | Path,
    registry_path: str | Path = "data/prereg_registry.jsonl",
    *,
    calibration_report_path: str | Path | None = None,
    prediction_path: str | Path | None = None,
    prediction_registry_path: str | Path = "data/prediction_registry.jsonl",
) -> dict:
    cfg=load_yaml(config_path)
    if cfg.get("status") != "READY_TO_FREEZE":
        raise RuntimeError("Spec is not READY_TO_FREEZE. Complete v0.15 calibration and fill the primary window/hedge venue first.")
    if not calibration_report_path:
        raise RuntimeError("A passing v0.15 calibration report is required before freeze.")
    report=_load_json(calibration_report_path)
    if report.get("status") != "PASS":
        raise RuntimeError("Calibration report did not PASS; primary experiment cannot be frozen.")
    if report.get("calibration_basis_sha256") != calibration_basis_hash(cfg):
        raise RuntimeError("Current design assumptions differ from the passing calibration report. Re-run v0.15 calibration before freeze.")
    selected_block = report.get("bootstrap",{}).get("selected_mean_block_swaps")
    configured_block = cfg.get("inference",{}).get("stationary_bootstrap_mean_block_swaps")
    if selected_block is None:
        raise RuntimeError("Calibration report is missing the selected stationary-bootstrap block length.")
    if configured_block is None or abs(float(configured_block)-float(selected_block)) > 1e-12:
        raise RuntimeError(
            "Set inference.stationary_bootstrap_mean_block_swaps to the exact outcome-blind value selected by the passing calibration report before freeze."
        )
    sample=cfg.get("sample",{})
    if not sample.get("start") or not sample.get("end"):
        raise RuntimeError("Primary sample start/end must be filled from the passing outcome-blind calibration window before freeze.")
    candidate=report.get("candidate_window",{})
    if str(sample.get("start")) != str(candidate.get("start")) or str(sample.get("end")) != str(candidate.get("end")):
        raise RuntimeError("Configured primary sample does not match the window that passed v0.15 calibration.")
    required_pred = prediction_path or cfg.get("prediction",{}).get("prediction_file")
    if cfg.get("prediction",{}).get("require_sealed_prediction_before_freeze",False):
        if not required_pred or not Path(required_pred).exists():
            raise RuntimeError("Prediction file is required before freeze.")
        pred_hash=file_sha256(required_pred)
        preg=Path(prediction_registry_path)
        sealed=[] if not preg.exists() else [json.loads(line) for line in preg.read_text().splitlines() if line.strip()]
        if not any(r.get("prediction_sha256")==pred_hash for r in sealed):
            raise RuntimeError("Prediction file has not been sealed. Run `houseedge seal-prediction` first.")
    rec={
        "experiment_id": cfg["experiment_id"],
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "spec_sha256": canonical_hash(cfg),
        "calibration_report_sha256": file_sha256(calibration_report_path),
        "prediction_sha256": file_sha256(required_pred) if required_pred else None,
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
        raise RuntimeError("No local preregistration record. Complete v0.15 and run `houseedge freeze` before the real experiment.")
    rows=[json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    match=[x for x in rows if x.get("experiment_id")==exp]
    if not match:
        raise RuntimeError(f"No preregistration record for {exp}")
    if match[-1]["spec_sha256"] != h:
        raise RuntimeError("Current config hash differs from frozen preregistration. Do not run under the same experiment ID.")


def register_outcome_look(experiment_id: str, registry_path: str | Path = "data/outcome_looks.jsonl", *, reason: str = "primary_run") -> dict:
    """Count every primary-outcome exposure. Post-unblind reruns are new looks."""
    p=Path(registry_path); p.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    if p.exists():
        rows=[json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    n=1+sum(1 for r in rows if r.get("experiment_id")==experiment_id)
    rec={"experiment_id":experiment_id,"look_number":n,"reason":reason,"opened_at_utc":datetime.now(timezone.utc).isoformat()}
    with p.open("a",encoding="utf-8") as f:
        f.write(json.dumps(rec,sort_keys=True)+"\n")
    return rec
