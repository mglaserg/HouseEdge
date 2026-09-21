from pathlib import Path

from houseedge.config import load_yaml


def test_experiment001_v022_frozen_calibration_choices():
    cfg=load_yaml("configs/experiment_001.yaml")
    assert cfg["spec_version"]=="0.2.2"
    assert cfg["pool"]["pool_address"].lower()=="0xd0b53d9277642d899df5c87a3966a349a798f224"
    assert cfg["calibration"]["calibration_window"]=={"start":"2025-07-01","end":"2025-12-31"}
    assert cfg["calibration"]["candidate_primary_window"]=={"start":"2026-01-01","end":"2026-08-31"}
    assert cfg["calibration"]["gate0"]["annual_variable_cost_yield_assumption"]==0.025
    assert cfg["calibration"]["gate0"]["annual_fixed_cost_usd"]==100.0
    assert cfg["sample"]["primary_reference"]=="MULTI_VENUE_SPOT_ETHUSDT_LAST_TRADE"
    assert cfg["sample"]["primary_reference_symbol"]=="ETHUSDT"
    assert cfg["sample"]["primary_alignment"]["quote"]=="last_trade"
    policy=cfg["sample"]["reference_policy"]
    assert [venue["id"] for venue in policy["venues"]]==["binance_spot","bybit_spot"]
    assert policy["selection_window"]=="calibration_only"
    assert policy["selection_status"]=="CALIBRATION_REQUIRED"
    assert cfg["validity"]["max_missing_reference_fraction"]==0.005
    assert cfg["hedge"]["venue"]=="HYPERLIQUID"
    assert cfg["hedge"]["taker_cost_bps"]==5.0
    assert cfg["hedge"]["expected_funding_interval_hours"]==1
    assert cfg["inference"]["stationary_bootstrap_mean_block_days"] is None

    assert cfg["historical_data"]["event_source"]=="HYPERSYNC"
    assert cfg["historical_data"]["hypersync"]["url"]=="https://base.hypersync.xyz"
    assert cfg["historical_data"]["hypersync"]["api_token_env"]=="ENVIO_API_TOKEN"
    assert cfg["historical_data"]["rpc_fallback_allowed"] is False


def test_reference_contract_matches_preregistration_text():
    cfg=load_yaml("configs/experiment_001.yaml")
    symbol=cfg["sample"]["primary_reference_symbol"]
    prereg=Path("prereg/experiment_001.md").read_text(encoding="utf-8")

    assert cfg["sample"]["primary_reference"]==f"MULTI_VENUE_SPOT_{symbol}_LAST_TRADE"
    assert f"{symbol[:3]}/{symbol[3:]}" in prereg
    assert "Bybit" in prereg
    assert "calibration window only" in prereg
    assert "last non-stale" in prereg
    assert "bid/ask midpoint" not in prereg
