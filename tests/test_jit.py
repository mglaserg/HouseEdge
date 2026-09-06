import pandas as pd
from houseedge.research.jit import jit_dilution_diagnostic


def test_short_lived_liquidity_overlaps_swap():
    e=pd.DataFrame([
        {"event":"Mint","block_number":10,"transaction_index":0,"log_index":0,"owner":"0xabc","tick_lower":-10,"tick_upper":10,"liquidity_delta":100.0},
        {"event":"Swap","block_number":11,"transaction_index":0,"log_index":0,"tick":0,"liquidity":1000.0},
        {"event":"Burn","block_number":12,"transaction_index":0,"log_index":0,"owner":"0xabc","tick_lower":-10,"tick_upper":10,"liquidity_delta":-100.0},
    ])
    swaps,s=jit_dilution_diagnostic(e,max_lifetime_blocks=3)
    assert s.swaps_with_jit_liquidity==1
    assert abs(swaps.iloc[0].jit_share_active-.1)<1e-12
