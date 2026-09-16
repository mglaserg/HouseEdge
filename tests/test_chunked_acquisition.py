import sys
import types
from pathlib import Path

import pandas as pd

from houseedge.data import acquire


def test_hypersync_event_dataset_writes_chunks_and_resumes(tmp_path, monkeypatch):
    calls=[]
    fake_hs=types.ModuleType('houseedge.data.hypersync_base')
    def fake_fetch(pool, spec, start, end, settings=None):
        calls.append((start,end))
        return pd.DataFrame([{
            'event':'Swap','block_number':start,'transaction_index':0,'log_index':0,
            'timestamp':pd.Timestamp('2026-01-01T00:00:00Z'),
            'amount0':1.0,'amount1':-3000.0,
        }])
    fake_hs.fetch_uniswap_v3_events=fake_fetch
    monkeypatch.setitem(sys.modules,'houseedge.data.hypersync_base',fake_hs)

    fake_uni=types.ModuleType('houseedge.data.uniswap_base')
    fake_uni.read_fee_protocol_at_block=lambda *a,**k: 0
    monkeypatch.setitem(sys.modules,'houseedge.data.uniswap_base',fake_uni)
    monkeypatch.setattr(acquire,'attach_protocol_fee_state',lambda df, initial: df.assign(fee_protocol_packed=0,lp_fee_fraction=1.0))

    def fake_write(df,path):
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'parquet-ish'); return path
    monkeypatch.setattr(acquire,'write_frame',fake_write)

    out=tmp_path/'events.parquet'
    acquire._fetch_hypersync_event_dataset(
        w3=object(),pool='0x'+'11'*20,spec=object(),b0=100,b1=349,
        settings=object(),dataset_dir=out,chunk_blocks=100,emit=lambda _:None,
    )
    assert calls == [(100,199),(200,299),(300,349)]
    assert len(list(out.glob('part-*.parquet'))) == 3
    assert (out/'_SUCCESS.json').exists()

    # A completed dataset is reused without refetching.
    acquire._fetch_hypersync_event_dataset(
        w3=object(),pool='0x'+'11'*20,spec=object(),b0=100,b1=349,
        settings=object(),dataset_dir=out,chunk_blocks=100,emit=lambda _:None,
    )
    assert calls == [(100,199),(200,299),(300,349)]
