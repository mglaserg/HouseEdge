import json
import yaml
import pytest
from houseedge.config import calibration_basis_hash
from houseedge.prereg import freeze_record, assert_frozen, seal_prediction, register_outcome_look


def test_prereg_requires_calibration_and_sealed_prediction(tmp_path):
    cfg = {
        "experiment_id": "X-1",
        "status": "READY_TO_FREEZE",
        "registered_at": None,
        "sample": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-01-31T00:00:00+00:00"},
        "inference": {"primary_trial_count": 1},
        "prediction": {"require_sealed_prediction_before_freeze": True, "prediction_file": str(tmp_path/"prediction.json")},
    }
    p = tmp_path / "cfg.yaml"
    r = tmp_path / "registry.jsonl"
    cr = tmp_path / "calibration.json"
    pred = tmp_path / "prediction.json"
    preg = tmp_path / "prediction_registry.jsonl"
    p.write_text(yaml.safe_dump(cfg))
    # calibration_basis_hash normalizes status and sample dates, so this report
    # remains valid when calibration selects the dates and status becomes READY.
    cr.write_text(json.dumps({
        "status":"PASS",
        "calibration_basis_sha256":calibration_basis_hash(cfg),
        "candidate_window":{"start":cfg["sample"]["start"],"end":cfg["sample"]["end"]},
    }))
    pred.write_text(json.dumps({"expected":"GO"}))
    with pytest.raises(RuntimeError):
        freeze_record(p,r,calibration_report_path=cr,prediction_registry_path=preg)
    seal_prediction(pred,preg)
    freeze_record(p,r,calibration_report_path=cr,prediction_registry_path=preg)
    assert_frozen(p,r)
    cfg["extra"] = "changed"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(RuntimeError):
        assert_frozen(p,r)


def test_outcome_looks_increment(tmp_path):
    r=tmp_path/"looks.jsonl"
    a=register_outcome_look("X",r)
    b=register_outcome_look("X",r,reason="bugfix_rerun")
    assert a["look_number"]==1
    assert b["look_number"]==2
