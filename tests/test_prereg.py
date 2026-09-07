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
        "inference": {"primary_trial_count": 1, "stationary_bootstrap_mean_block_swaps": 17.0},
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
        "bootstrap":{"selected_mean_block_swaps":17.0},
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

from houseedge.prereg import apply_calibration_selection


def test_prepare_freeze_applies_only_calibration_selected_fields(tmp_path):
    cfg={
        "experiment_id":"X-2","status":"CALIBRATION_REQUIRED","registered_at":None,
        "sample":{"start":None,"end":None},
        "inference":{"primary_trial_count":1,"stationary_bootstrap_mean_block_swaps":None},
    }
    p=tmp_path/"cfg.yaml"; p.write_text(yaml.safe_dump(cfg))
    report={
        "status":"PASS","calibration_basis_sha256":calibration_basis_hash(cfg),
        "candidate_window":{"start":"2026-01-01T00:00:00+00:00","end":"2026-08-31T23:59:59+00:00"},
        "bootstrap":{"selected_mean_block_swaps":23.0},
    }
    r=tmp_path/"cal.json"; r.write_text(json.dumps(report))
    out=apply_calibration_selection(p,r)
    selected=yaml.safe_load(p.read_text())
    assert out["status"]=="READY_TO_FREEZE"
    assert selected["sample"]["start"]==report["candidate_window"]["start"]
    assert selected["inference"]["stationary_bootstrap_mean_block_swaps"]==23.0
    assert calibration_basis_hash(selected)==report["calibration_basis_sha256"]
