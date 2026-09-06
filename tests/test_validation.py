from houseedge.research.validation import evaluate_void_criteria


def test_void_is_distinct_from_kill():
    r=evaluate_void_criteria(missing_reference_fraction=.01,max_missing_reference_fraction=.005,funding_gap_hours=0,max_funding_gap_hours=0,protocol_fee_history_complete=True,replay_state_valid=True,micro_live_fee_error_bps_nav=0,max_micro_live_fee_error_bps_nav=1)
    assert r.status=="VOID"
    assert "REFERENCE_COVERAGE" in r.failures
