import pandas as pd
from houseedge.research.benchmark import time_weighted_apy_return


def test_constant_apy_one_year():
    rates=pd.DataFrame({"timestamp":[pd.Timestamp("2025-12-31T00:00:00Z")],"apy":[0.10]})
    start=pd.Timestamp("2026-01-01T00:00:00Z"); end=start+pd.Timedelta(days=365)
    window,ann=time_weighted_apy_return(rates,start,end)
    assert abs(window-.10)<1e-10
    assert abs(ann-.10)<1e-10
