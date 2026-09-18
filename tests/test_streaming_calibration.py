from pathlib import Path
import pandas as pd

from houseedge.config import load_yaml
from houseedge.demo import synthetic_tape
from houseedge.data import acquire


def test_partitioned_calibration_replay_produces_daily_increments(tmp_path, monkeypatch):
    swaps, ref = synthetic_tape(n=500)
    frames=[]; refs=[]
    for j in range(4):
        shift=pd.Timedelta(days=3*j)
        x=swaps.copy()
        x["timestamp"]=pd.to_datetime(x["timestamp"],utc=True)+shift
        x["block_number"]=x["block_number"]+j*200_000
        x["log_index"]=x["log_index"]+j*1_000_000
        x["fee_protocol_packed"]=0; x["lp_fee_fraction"]=1.0
        r=ref.copy(); r["timestamp"]=pd.to_datetime(r["timestamp"],utc=True)+shift
        r["alignment_eligible"]=True; r["regime_eligible"]=True
        frames.append(x); refs.append(r)
        (tmp_path/f"part-{j:03d}.parquet").write_bytes(b"fixture")
    ref_all=pd.concat(refs,ignore_index=True).sort_values("timestamp")
    start=frames[0]["timestamp"].min(); end=frames[-1]["timestamp"].max()
    funding=pd.DataFrame({"timestamp":pd.date_range(pd.Timestamp(start).ceil("h"),pd.Timestamp(end).floor("h"),freq="1h",tz="UTC"),"funding_rate":0.0})
    bench=pd.DataFrame({"timestamp":[pd.Timestamp(start)-pd.Timedelta(hours=1)],"apy":[0.04]})
    mapping={str(tmp_path/f"part-{j:03d}.parquet"):frames[j] for j in range(4)}
    monkeypatch.setattr(acquire.pd,"read_parquet",lambda path,*a,**k:mapping[str(Path(path))].copy())
    out=acquire.derive_calibration_excess_increments_from_dataset(tmp_path,ref_all,funding,bench,load_yaml("configs/experiment_001.yaml"))
    assert len(out)>=10
    assert out["timestamp"].is_monotonic_increasing
    assert out["timestamp"].dt.hour.eq(0).all()
    assert out["excess_return_inc"].notna().all()
