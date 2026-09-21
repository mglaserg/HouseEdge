import gzip

import pandas as pd

from houseedge.data.bybit_public import load_last_trades_for_targets


def test_bybit_archive_matching_is_backward_only(tmp_path):
    archive=tmp_path/"ETHUSDT-2026-01.csv.gz"
    with gzip.open(archive,"wt",encoding="utf-8",newline="") as stream:
        stream.write("id,timestamp,price,volume,side,rpi\n")
        stream.write("1,1767225601000,3000.0,1,Buy,false\n")
        stream.write("2,1767225602000,3001.0,1,Sell,false\n")

    targets=pd.to_datetime(
        ["2026-01-01T00:00:01.500Z","2026-01-01T00:00:02.500Z"],utc=True
    )
    result=load_last_trades_for_targets(
        "ETHUSDT",targets,tmp_path,max_age_seconds=1.0
    )

    assert result["mid"].tolist()==[3000.0,3001.0]
    assert (result["timestamp"]<=result["target_timestamp"]).all()
    assert result["age_seconds"].tolist()==[0.5,0.5]
    assert set(result["source"])=={"bybit_spot_trade"}
