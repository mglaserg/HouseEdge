import sys
import types
from pathlib import Path

import pandas as pd

from houseedge.config import load_yaml
from houseedge.data import acquire


def test_hypersync_acquisition_skips_rpc_log_probe(tmp_path, monkeypatch):
    cfg = load_yaml("configs/experiment_001.yaml")
    fake_w3 = object()
    calls = {"events": 0, "preflight": 0, "aave": 0}

    fake_uniswap = types.ModuleType("houseedge.data.uniswap_base")
    fake_uniswap.connect = lambda rpc_url=None: fake_w3
    fake_uniswap.fetch_events = lambda *a, **k: (_ for _ in ()).throw(AssertionError("RPC log fetch must not run"))
    fake_uniswap.read_fee_protocol_at_block = lambda *a, **k: 0
    monkeypatch.setitem(sys.modules, "houseedge.data.uniswap_base", fake_uniswap)

    fake_hs = types.ModuleType("houseedge.data.hypersync_base")
    fake_settings = types.SimpleNamespace(url="https://base.hypersync.xyz")
    fake_hs.settings_from_config = lambda cfg: fake_settings
    def fake_preflight(settings):
        calls["preflight"] += 1
        return {"ok": True, "chain_id": 8453, "archive_height": 123456, "url": settings.url}
    fake_hs.preflight = fake_preflight
    def fake_fetch_events(pool, spec, b0, b1, settings=None):
        calls["events"] += 1
        year = 2025 if calls["events"] == 1 else 2026
        return pd.DataFrame([{
            "event": "Swap", "block_number": b0, "transaction_index": 0, "log_index": 0,
            "timestamp": pd.Timestamp(f"{year}-08-01T00:00:00Z"),
            "amount0": 1.0, "amount1": -3000.0, "sqrt_price_x96": 1,
            "liquidity": 1000, "tick": 0,
        }])
    fake_hs.fetch_uniswap_v3_events = fake_fetch_events
    monkeypatch.setitem(sys.modules, "houseedge.data.hypersync_base", fake_hs)

    fake_aave = types.ModuleType("houseedge.data.aave_base")
    fake_aave.fetch_usdc_supply_rates = lambda *a, **k: (_ for _ in ()).throw(AssertionError("RPC Aave logs must not run"))
    def fake_aave_hs(*a, **k):
        calls["aave"] += 1
        return pd.DataFrame({"timestamp": [pd.Timestamp("2025-07-01T00:00:00Z")], "apy": [0.04]})
    fake_aave.fetch_usdc_supply_rates_hypersync = fake_aave_hs
    monkeypatch.setitem(sys.modules, "houseedge.data.aave_base", fake_aave)

    monkeypatch.setattr(acquire, "block_at_or_after", lambda w3, t: 100 if pd.Timestamp(t).year == 2025 else 200)
    monkeypatch.setattr(acquire, "block_at_or_before", lambda w3, t: 150 if pd.Timestamp(t).year == 2025 else 250)
    monkeypatch.setattr(acquire, "validate_historical_log_plan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("RPC log probe must not run")))
    monkeypatch.setattr(acquire, "attach_protocol_fee_state", lambda df, initial: df.assign(fee_protocol_packed=0, lp_fee_fraction=1.0))
    monkeypatch.setattr(acquire, "build_reference", lambda *a, **k: pd.DataFrame({
        "timestamp": [pd.Timestamp("2025-08-01T00:00:00Z") if calls["events"] == 1 else pd.Timestamp("2026-08-01T00:00:00Z")],
        "mid": [3000.0], "alignment_eligible": [True], "regime_eligible": [True],
    }))
    monkeypatch.setattr(acquire, "fetch_funding_history", lambda *a, **k: pd.DataFrame({"timestamp": [pd.Timestamp("2025-07-01T00:00:00Z")], "funding_rate": [0.0]}))
    monkeypatch.setattr(acquire, "derive_calibration_excess_increments", lambda *a, **k: pd.DataFrame({"timestamp": [pd.Timestamp("2025-07-01T00:00:00Z")], "excess_return_inc": [0.0]}))

    def fake_write(df, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
        return path
    monkeypatch.setattr(acquire, "write_frame", fake_write)

    manifest = acquire.acquire_v015_inputs(cfg, output_root=tmp_path)
    assert calls == {"events": 2, "preflight": 1, "aave": 2}
    assert manifest["sources"]["bulk_historical_source"] == "HYPERSYNC"
    assert manifest["sources"]["hypersync_chain_id"] == 8453
    assert manifest["sources"]["rpc_role"] == "state_validation_and_block_boundaries_only"
    assert "rpc_effective_log_chunk_blocks" not in manifest["sources"]
    assert manifest["candidate_primary_pnl_opened"] is False
    assert "raw/candidate_events.parquet" in manifest["outputs"]
    assert "secret" not in str(manifest)
