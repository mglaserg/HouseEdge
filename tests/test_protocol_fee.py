import pandas as pd
from houseedge.research.protocol_fee import attach_protocol_fee_state, pack_fee_protocol, lp_fee_fraction_for_swap


def test_protocol_fee_direction_and_history():
    assert lp_fee_fraction_for_swap(pack_fee_protocol(4,6),1,-1)==0.75
    assert abs(lp_fee_fraction_for_swap(pack_fee_protocol(4,6),-1,1)-(5/6))<1e-12
    events=pd.DataFrame([
        {"event":"Swap","block_number":1,"transaction_index":0,"log_index":0,"amount0":1.0,"amount1":-1.0},
        {"event":"SetFeeProtocol","block_number":2,"transaction_index":0,"log_index":0,"fee_protocol0_new":5,"fee_protocol1_new":0},
        {"event":"Swap","block_number":3,"transaction_index":0,"log_index":0,"amount0":1.0,"amount1":-1.0},
    ])
    x=attach_protocol_fee_state(events,pack_fee_protocol(4,6))
    swaps=x[x.event.eq("Swap")]
    assert abs(swaps.iloc[0].lp_fee_fraction-.75)<1e-12
    assert abs(swaps.iloc[1].lp_fee_fraction-.80)<1e-12
