from houseedge.config import load_yaml


def test_experiment001_v016_frozen_calibration_choices():
    cfg=load_yaml("configs/experiment_001.yaml")
    assert cfg["spec_version"]=="0.1.6"
    assert cfg["pool"]["pool_address"].lower()=="0xd0b53d9277642d899df5c87a3966a349a798f224"
    assert cfg["calibration"]["calibration_window"]=={"start":"2025-07-01","end":"2025-12-31"}
    assert cfg["calibration"]["candidate_primary_window"]=={"start":"2026-01-01","end":"2026-08-31"}
    assert cfg["calibration"]["gate0"]["annual_variable_cost_yield_assumption"]==0.025
    assert cfg["calibration"]["gate0"]["annual_fixed_cost_usd"]==100.0
    assert cfg["sample"]["primary_reference"]=="BINANCE_SPOT_ETHUSDC"
    assert cfg["sample"]["primary_alignment"]["quote"]=="last_trade"
    assert cfg["hedge"]["venue"]=="HYPERLIQUID"
    assert cfg["hedge"]["taker_cost_bps"]==5.0
    assert cfg["hedge"]["expected_funding_interval_hours"]==1
    assert cfg["inference"]["stationary_bootstrap_mean_block_swaps"] is None
