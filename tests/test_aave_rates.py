from houseedge.data.aave_base import ray_apr_to_apy, RAY


def test_aave_ray_apr_to_apy():
    apy=ray_apr_to_apy(int(0.05*RAY))
    assert 0.0512 < apy < 0.0514
