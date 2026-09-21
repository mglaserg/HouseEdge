import json

from typer.testing import CliRunner

from houseedge.cli import app
from houseedge.data import fair_value


def test_rebuild_references_command_reports_gate(monkeypatch):
    called={}

    def fake_rebuild(**kwargs):
        called.update(kwargs)
        return {
            "status":"PASS",
            "allowed_missing_fraction":0.005,
            "candidate_primary_lp_pnl_opened":False,
        }

    monkeypatch.setattr(fair_value,"rebuild_multi_venue_references",fake_rebuild)
    result=CliRunner().invoke(app,["rebuild-references"])

    assert result.exit_code==0
    payload=json.loads(result.stdout[result.stdout.index("{"):])
    assert payload["status"]=="PASS"
    assert payload["allowed_missing_fraction"]==0.005
    assert called["output_root"]=="data"
