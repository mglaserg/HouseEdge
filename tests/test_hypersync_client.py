import asyncio
import sys
import types

import pandas as pd

from houseedge.data import hypersync_base as hs


class _Ctor:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Receiver:
    def __init__(self, responses):
        self.responses = list(responses)

    async def recv(self):
        if not self.responses:
            return None
        return self.responses.pop(0)


def _fake_module(captured, chain_id=8453):
    mod = types.ModuleType("hypersync")
    mod.ClientConfig = _Ctor
    mod.LogSelection = _Ctor
    mod.FieldSelection = _Ctor
    mod.Query = _Ctor
    mod.StreamConfig = _Ctor
    mod.BlockField = types.SimpleNamespace(NUMBER="number", TIMESTAMP="timestamp")
    mod.LogField = types.SimpleNamespace(
        BLOCK_NUMBER="block_number", LOG_INDEX="log_index", TRANSACTION_INDEX="transaction_index",
        TRANSACTION_HASH="transaction_hash", BLOCK_HASH="block_hash", DATA="data", ADDRESS="address",
        TOPIC0="topic0", TOPIC1="topic1", TOPIC2="topic2", TOPIC3="topic3",
    )

    class Client:
        def __init__(self, config):
            captured["client_config"] = config

        async def get_chain_id(self):
            return chain_id

        async def get_height(self):
            return 999

        async def stream(self, query, stream_config):
            captured["query"] = query
            captured["stream_config"] = stream_config
            block = types.SimpleNamespace(number=10, timestamp=1_700_000_000)
            log = types.SimpleNamespace(block_number=10, log_index=1, transaction_index=2)
            response = types.SimpleNamespace(data=types.SimpleNamespace(blocks=[block], logs=[log]))
            return _Receiver([response])

    mod.HypersyncClient = Client
    return mod


def test_hypersync_preflight_uses_token_and_base_chain(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "hypersync", _fake_module(captured))
    monkeypatch.setenv("ENVIO_API_TOKEN", "secret-test-token")
    result = hs.preflight(hs.HyperSyncSettings())
    assert result == {"url": "https://base.hypersync.xyz", "chain_id": 8453, "archive_height": 999, "ok": True}
    assert captured["client_config"].bearer_token == "secret-test-token"


def test_hypersync_query_uses_exclusive_to_block_and_joined_timestamps(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "hypersync", _fake_module(captured))
    monkeypatch.setenv("ENVIO_API_TOKEN", "secret-test-token")
    monkeypatch.setattr(
        hs,
        "_raw_log_to_dict",
        lambda log, ts: {
            "blockNumber": int(log.block_number),
            "transactionIndex": int(log.transaction_index),
            "logIndex": int(log.log_index),
            "timestamp": ts[int(log.block_number)],
        },
    )
    rows = asyncio.run(hs._stream_raw_logs_async(
        address="0x0000000000000000000000000000000000000001",
        topic_filters=[["0x" + "11" * 32]],
        from_block=10,
        to_block=20,
        settings=hs.HyperSyncSettings(),
    ))
    query = captured["query"]
    assert query.from_block == 10
    assert query.to_block == 21
    assert query.logs[0].topics == [["0x" + "11" * 32]]
    assert rows[0]["timestamp"] == pd.Timestamp(1_700_000_000, unit="s", tz="UTC")
