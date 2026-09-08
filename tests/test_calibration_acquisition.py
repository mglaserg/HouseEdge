import pandas as pd

from houseedge.config import load_yaml
from houseedge.data.acquire import derive_calibration_excess_increments
from houseedge.demo import synthetic_tape


def test_calibration_increments_are_derived_without_candidate_outcome():
    swaps,ref=synthetic_tape(n=300)
    swaps=swaps.copy()
    swaps["fee_protocol_packed"]=0
    swaps["lp_fee_fraction"]=1.0
    ref=ref.copy()
    ref["alignment_eligible"]=True
    ref["regime_eligible"]=True
    start=pd.Timestamp(swaps.timestamp.min())
    end=pd.Timestamp(swaps.timestamp.max())
    funding=pd.DataFrame({
        "timestamp":pd.date_range(start.ceil("h"),end,freq="1h",tz="UTC"),
        "funding_rate":0.0,
    })
    bench=pd.DataFrame({"timestamp":[start-pd.Timedelta(hours=1)],"apy":[0.04]})
    cfg=load_yaml("configs/experiment_001.yaml")
    out=derive_calibration_excess_increments(swaps,ref,funding,bench,cfg)
    assert len(out)>100
    assert set(out.columns)=={"timestamp","excess_return_inc"}
    assert out["excess_return_inc"].notna().all()
