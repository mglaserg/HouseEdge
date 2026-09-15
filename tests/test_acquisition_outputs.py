from pathlib import Path
import pandas as pd
from typer.testing import CliRunner

from houseedge.data.storage import write_frame
from houseedge.cli import app


def test_write_frame_materializes_nonempty_parquet(tmp_path):
    p=write_frame(pd.DataFrame({'x':[1,2]}), tmp_path/'x.parquet')
    assert p.exists()
    assert p.stat().st_size>0
    assert not (tmp_path/'x.parquet.tmp').exists()


def test_fetch_calibration_cli_prints_absolute_output_and_status_on_failure(tmp_path, monkeypatch):
    import houseedge.data.acquire as acquire
    def boom(*args, **kwargs):
        raise RuntimeError('synthetic acquisition failure')
    monkeypatch.setattr(acquire,'acquire_v015_inputs',boom)
    runner=CliRunner()
    out=tmp_path/'relative-ish'
    result=runner.invoke(app,['fetch-calibration-data','--output-root',str(out)])
    assert result.exit_code != 0
    status=out.resolve()/'v015_acquisition_status.json'
    assert status.exists()
    text=status.read_text()
    assert 'FAILED' in text
    assert 'synthetic acquisition failure' in text
    assert str(out.resolve()) in result.stdout
