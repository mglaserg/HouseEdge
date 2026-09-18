import pandas as pd

from houseedge.data.storage import parquet_safe_frame


def test_parquet_safe_frame_serializes_evm_wide_ints_losslessly():
    sqrt_price = 2**159 + 12345
    liquidity = 2**127 + 77
    amount_raw = 2**255 - 19
    df = pd.DataFrame({
        "block_number": [123],
        "sqrt_price_x96": [sqrt_price],
        "liquidity": [liquidity],
        "amount0_raw": [amount_raw],
        "small": [42],
    })

    safe = parquet_safe_frame(df)

    assert safe.loc[0, "sqrt_price_x96"] == str(sqrt_price)
    assert safe.loc[0, "liquidity"] == str(liquidity)
    assert safe.loc[0, "amount0_raw"] == str(amount_raw)
    assert safe.loc[0, "small"] == 42
    assert int(safe.loc[0, "sqrt_price_x96"]) == sqrt_price
    assert int(safe.loc[0, "liquidity"]) == liquidity
    assert int(safe.loc[0, "amount0_raw"]) == amount_raw


def test_parquet_safe_frame_handles_sparse_wide_integer_columns():
    huge = 2**140
    df = pd.DataFrame({"event": ["Swap", "Mint"], "liquidity": [huge, None]})
    safe = parquet_safe_frame(df)
    assert safe.loc[0, "liquidity"] == str(huge)
    assert pd.isna(safe.loc[1, "liquidity"])


def test_write_frame_roundtrips_evm_wide_ints_when_pyarrow_available(tmp_path):
    import pytest
    pytest.importorskip("pyarrow")
    from houseedge.data.storage import write_frame, read_frame

    huge = 2**200 + 123
    path = write_frame(pd.DataFrame({"wide": [huge], "small": [7]}), tmp_path / "wide.parquet")
    restored = read_frame(path)
    assert int(restored.loc[0, "wide"]) == huge
    assert int(restored.loc[0, "small"]) == 7
