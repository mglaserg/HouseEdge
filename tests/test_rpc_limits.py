from types import SimpleNamespace
import pytest

from houseedge.data.base_rpc import probe_log_block_limit, validate_historical_log_plan


class FakeProvider:
    def __init__(self, max_blocks, endpoint="https://base-mainnet.g.alchemy.com/v2/redacted"):
        self.max_blocks=max_blocks
        self.endpoint_uri=endpoint
    def make_request(self, method, params):
        f=params[0]
        n=int(f["toBlock"],16)-int(f["fromBlock"],16)+1
        if n>self.max_blocks:
            raise RuntimeError("400 block range too wide")
        return {"jsonrpc":"2.0","id":1,"result":[]}


class FakeW3:
    def __init__(self,max_blocks):
        self.provider=FakeProvider(max_blocks)
        self.eth=SimpleNamespace(block_number=50_000_000)


def test_probe_detects_alchemy_free_ten_block_limit():
    w3=FakeW3(10)
    assert probe_log_block_limit(w3,"0x"+"11"*20,10_000)==10


def test_historical_plan_rejects_impractical_tiny_log_range():
    w3=FakeW3(10)
    with pytest.raises(RuntimeError, match="not a practical backfill path"):
        validate_historical_log_plan(w3,"0x"+"11"*20,requested_chunk_blocks=10_000,total_blocks=18_000_000)


def test_historical_plan_keeps_large_supported_range():
    w3=FakeW3(10_000)
    assert validate_historical_log_plan(w3,"0x"+"11"*20,requested_chunk_blocks=10_000,total_blocks=18_000_000)==10_000
