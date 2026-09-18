import pandas as pd
from houseedge.research.alignment import align_reference


def test_primary_alignment_never_looks_forward():
    swaps=pd.DataFrame({"timestamp":[pd.Timestamp("2026-01-01T00:00:02Z")],"amount0":[1.0],"amount1":[-1.0]})
    ref=pd.DataFrame({"timestamp":[pd.Timestamp("2026-01-01T00:00:01Z"),pd.Timestamp("2026-01-01T00:00:02.100Z")],"mid":[100.0,999.0]})
    a=align_reference(swaps,ref,tolerance_seconds=3)
    assert a.iloc[0].ref_mid==100.0
    assert a.iloc[0].quote_age_seconds==1.0

from houseedge.data.reference import normalize_reference


def test_trade_price_reference_is_supported_and_backward_only():
    ref=normalize_reference(pd.DataFrame({
        "timestamp":[pd.Timestamp("2026-01-01T00:00:01Z"),pd.Timestamp("2026-01-01T00:00:03Z")],
        "price":[100.0,999.0],
        "source":["binance","binance"],
    }))
    swaps=pd.DataFrame({"timestamp":[pd.Timestamp("2026-01-01T00:00:02Z")],"amount0":[1.0],"amount1":[-1.0]})
    a=align_reference(swaps,ref,tolerance_seconds=3)
    assert a.iloc[0].ref_mid==100.0


def test_alignment_normalizes_mixed_datetime_resolutions():
    swaps=pd.DataFrame({
        "timestamp":pd.Series([pd.Timestamp("2026-01-01T00:00:02Z")],dtype="datetime64[ms, UTC]"),
        "amount0":[1.0],
        "amount1":[-1.0],
    })
    ref=pd.DataFrame({
        "timestamp":pd.Series([pd.Timestamp("2026-01-01T00:00:01Z")],dtype="datetime64[us, UTC]"),
        "mid":[100.0],
    })
    a=align_reference(swaps,ref,tolerance_seconds=3)
    assert a.iloc[0].ref_mid==100.0
    assert str(a["timestamp"].dtype)=="datetime64[ns, UTC]"
    assert str(a["quote_timestamp"].dtype)=="datetime64[ns, UTC]"
