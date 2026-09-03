import numpy as np
from houseedge.demo import synthetic_tape
from houseedge.research.alignment import align_reference
from houseedge.research.markouts import compute_markouts, shuffled_direction_null


def test_markouts_and_null_are_constructed():
    swaps, ref = synthetic_tape(n=500)
    aligned = align_reference(swaps, ref, tolerance_seconds=1)
    m = compute_markouts(aligned, ref, [30, 60], future_tolerance_seconds=1)
    assert {"info_markout_30s_bps", "execution_markout_60s_bps"}.issubset(m.columns)
    null = shuffled_direction_null(m, [30], reps=200, seed=123)
    assert len(null) == 1
    assert np.isfinite(null.loc[0, "null_mean_bps"])
