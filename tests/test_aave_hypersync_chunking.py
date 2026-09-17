import pandas as pd
import sys
import types

from houseedge.data import aave_base


class _ProviderCall:
    def call(self, block_identifier=None):
        return [0, 0, 0, 0, 0, int(0.04 * aave_base.RAY), 0, 0, 0, 0, 0, 0]


class _Functions:
    def getReserveData(self, asset):
        return _ProviderCall()


class _Contract:
    functions = _Functions()


class _Eth:
    def contract(self, address=None, abi=None):
        return _Contract()


class _W3:
    eth = _Eth()


def _event(block):
    return ({
        "args": {"liquidityRate": int(0.05 * aave_base.RAY)},
        "blockNumber": block,
        "transactionIndex": 0,
        "logIndex": 0,
    }, pd.Timestamp("2026-01-01T00:00:00Z"))


def test_aave_hypersync_is_chunked_and_retries(monkeypatch):
    fake_web3 = types.ModuleType("web3")
    class _Web3:
        @staticmethod
        def to_checksum_address(value):
            return value
    fake_web3.Web3 = _Web3
    monkeypatch.setitem(sys.modules, "web3", fake_web3)

    calls = []
    failures = {100: 1}

    monkeypatch.setattr(aave_base, "block_timestamp", lambda w3, block: pd.Timestamp("2025-12-31T23:59:59Z"))

    import houseedge.data.hypersync_base as hs
    monkeypatch.setattr(hs, "indexed_address_topic", lambda asset: "0x" + "00" * 32)

    def fake_fetch(**kwargs):
        start, end = kwargs["from_block"], kwargs["to_block"]
        calls.append((start, end))
        if failures.get(start, 0):
            failures[start] -= 1
            raise RuntimeError("read response body bytes")
        return [_event(start)]

    monkeypatch.setattr(hs, "fetch_decoded_event_logs", fake_fetch)
    monkeypatch.setattr("time.sleep", lambda _: None)

    out = aave_base.fetch_usdc_supply_rates_hypersync(
        _W3(), 100, 349, settings=object(), chunk_blocks=100, max_retries=2
    )

    assert calls == [(100, 199), (100, 199), (200, 299), (300, 349)]
    assert len(out) == 4  # seed + 3 rate updates
    assert out["block_number"].tolist() == [99, 100, 200, 300]
