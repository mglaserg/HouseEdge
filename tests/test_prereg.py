from pathlib import Path
import yaml
import pytest
from houseedge.prereg import freeze_record, assert_frozen


def test_prereg_hash_blocks_same_id_edits(tmp_path):
    cfg = {
        "experiment_id": "X-1",
        "status": "FROZEN",
        "inference": {"primary_trial_count": 1},
    }
    p = tmp_path / "cfg.yaml"
    r = tmp_path / "registry.jsonl"
    p.write_text(yaml.safe_dump(cfg))
    freeze_record(p, r)
    assert_frozen(p, r)
    cfg["extra"] = "changed"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(RuntimeError):
        assert_frozen(p, r)
