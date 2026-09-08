import pandas as pd

from houseedge.research.alignment import align_reference
from houseedge.research.regime import daily_realized_variance


def test_alignment_ignores_regime_only_rows():
    swaps=pd.DataFrame([{"timestamp":"2026-01-01T00:05:00Z","amount0":1.0,"amount1":-3000.0}])
    ref=pd.DataFrame([
        {"timestamp":"2026-01-01T00:04:59.999999Z","mid":9999.0,"alignment_eligible":False,"regime_eligible":True},
        {"timestamp":"2026-01-01T00:04:58Z","mid":3000.0,"alignment_eligible":True,"regime_eligible":False},
    ])
    out=align_reference(swaps,ref,tolerance_seconds=3)
    assert out.iloc[0].ref_mid==3000.0


def test_regime_uses_regime_only_rows_when_flag_present():
    t=pd.date_range("2026-01-01",periods=24*12*2,freq="5min",tz="UTC")
    regime=pd.DataFrame({"timestamp":t,"mid":3000*(1+pd.Series(range(len(t))).to_numpy()*1e-6),"regime_eligible":True})
    noise=pd.DataFrame({"timestamp":t[:5],"mid":[100,10000,100,10000,100],"regime_eligible":False})
    rv=daily_realized_variance(pd.concat([regime,noise],ignore_index=True),5)
    assert len(rv)>=1
    assert float(rv.max())<1.0
