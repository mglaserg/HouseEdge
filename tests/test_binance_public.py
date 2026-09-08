from pathlib import Path
import zipfile

import pandas as pd

from houseedge.data.binance_public import _epoch_us, build_reference, load_last_trades_for_targets


def _write_zip(path: Path, member: str, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, text)


def test_sparse_binance_reference_from_cached_archives(tmp_path):
    cache=tmp_path/"cache"
    agg=cache/"ETHUSDC-aggTrades-2026-01.zip"
    _write_zip(agg,"ETHUSDC-aggTrades-2026-01.csv", "\n".join([
        "1,3000,1,1,1,1767225600000000,False,True",
        "2,3001,1,2,2,1767225601500000,False,True",
        "3,3002,1,3,3,1767225603900000,False,True",
    ]))
    k=cache/"ETHUSDC-5m-2026-01.zip"
    _write_zip(k,"ETHUSDC-5m-2026-01.csv", "1767225600000000,3000,3002,2999,3001,10,1767225899999999,1,2,1,1,0\n")
    targets=pd.to_datetime(["2026-01-01T00:00:02Z","2026-01-01T00:00:04Z"],utc=True)
    exact=load_last_trades_for_targets("ETHUSDC",targets,cache,max_age_seconds=3)
    assert exact["mid"].tolist()==[3001.0,3002.0]
    ref=build_reference("ETHUSDC","2026-01-01","2026-01-01T00:05:00Z",targets,cache,max_age_seconds=3)
    assert ref["alignment_eligible"].fillna(False).sum()==2
    assert ref["regime_eligible"].fillna(False).sum()==1


def test_epoch_us_is_explicitly_resolution_independent():
    # Regression for pandas 3, which may preserve datetime64[us] and therefore
    # makes ``astype("int64") // 1000`` off by 1000.
    raw = pd.Series(pd.array([
        "2026-01-01T00:00:02Z",
        "2026-01-01T00:00:04Z",
    ], dtype="datetime64[us, UTC]"))
    assert _epoch_us(raw).tolist() == [1767225602000000, 1767225604000000]
