import sys
import types
from pathlib import Path

import pandas as pd

from houseedge.config import load_yaml
from houseedge.data import acquire


def test_acquisition_manifest_stays_outcome_blind(tmp_path, monkeypatch):
    cfg=load_yaml("configs/experiment_001.yaml")
    cfg["historical_data"]["event_source"]="RPC"
    fake_w3=object()
    calls={"n":0}

    def fake_fetch_events(w3,pool,spec,b0,b1,chunk_blocks=0,workers=0):
        calls["n"]+=1
        year=2025 if calls["n"]==1 else 2026
        t=pd.Timestamp(f"{year}-08-01T00:00:00Z")
        return pd.DataFrame([{
            "event":"Swap","block_number":b0,"transaction_index":0,"log_index":0,"timestamp":t,
            "amount0":1.0,"amount1":-3000.0,"sqrt_price_x96":1,"liquidity":1000,"tick":0,
        }])

    fake_uniswap=types.ModuleType("houseedge.data.uniswap_base")
    fake_uniswap.connect=lambda rpc_url=None: fake_w3
    fake_uniswap.fetch_events=fake_fetch_events
    fake_uniswap.read_fee_protocol_at_block=lambda *a,**k: 0
    monkeypatch.setitem(sys.modules,"houseedge.data.uniswap_base",fake_uniswap)
    monkeypatch.setattr(acquire,"block_at_or_after",lambda w3,t: 100 if pd.Timestamp(t).year==2025 else 200)
    monkeypatch.setattr(acquire,"block_at_or_before",lambda w3,t: 150 if pd.Timestamp(t).year==2025 else 250)
    monkeypatch.setattr(acquire,"attach_protocol_fee_state",lambda df,initial: df.assign(fee_protocol_packed=0,lp_fee_fraction=1.0))
    monkeypatch.setattr(acquire,"build_reference",lambda *a,**k: pd.DataFrame({
        "timestamp":[pd.Timestamp("2025-08-01T00:00:00Z") if calls["n"]==1 else pd.Timestamp("2026-08-01T00:00:00Z")],
        "mid":[3000.0],"alignment_eligible":[True],"regime_eligible":[True]
    }))
    monkeypatch.setattr(acquire,"fetch_usdc_supply_rates",lambda *a,**k: pd.DataFrame({"timestamp":[pd.Timestamp("2025-07-01T00:00:00Z")],"apy":[0.04]}))
    monkeypatch.setattr(acquire,"fetch_funding_history",lambda *a,**k: pd.DataFrame({"timestamp":[pd.Timestamp("2025-07-01T00:00:00Z")],"funding_rate":[0.0]}))
    monkeypatch.setattr(acquire,"derive_calibration_excess_increments",lambda *a,**k: pd.DataFrame({"timestamp":[pd.Timestamp("2025-07-01T00:00:00Z")],"excess_return_inc":[0.0]}))

    def fake_write(df,path):
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b"test"); return path
    monkeypatch.setattr(acquire,"write_frame",fake_write)

    manifest=acquire.acquire_v015_inputs(cfg,output_root=tmp_path)
    assert manifest["outcome_blind"] is True
    assert manifest["candidate_primary_pnl_opened"] is False
    assert "raw/candidate_events.parquet" in manifest["outputs"]
    assert (tmp_path/"v015_acquisition_manifest.json").exists()
