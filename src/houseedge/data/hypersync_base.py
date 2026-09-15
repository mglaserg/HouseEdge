from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

DEFAULT_BASE_HYPERSYNC_URL = "https://base.hypersync.xyz"
DEFAULT_TOKEN_ENV = "ENVIO_API_TOKEN"


@dataclass(frozen=True)
class HyperSyncSettings:
    url: str = DEFAULT_BASE_HYPERSYNC_URL
    token_env: str = DEFAULT_TOKEN_ENV
    require_chain_id: int = 8453

    def token(self) -> str:
        value = os.environ.get(self.token_env)
        if not value:
            raise RuntimeError(
                f"HyperSync requires {self.token_env}. Create an Envio API token and set "
                f"`export {self.token_env}=...` before running the historical backfill."
            )
        return value


def settings_from_config(cfg: dict) -> HyperSyncSettings:
    h = cfg.get("historical_data", {}).get("hypersync", {})
    return HyperSyncSettings(
        url=str(h.get("url") or DEFAULT_BASE_HYPERSYNC_URL).rstrip("/"),
        token_env=str(h.get("api_token_env") or DEFAULT_TOKEN_ENV),
        require_chain_id=int(h.get("require_chain_id", 8453)),
    )


def _hypersync_module():
    try:
        import hypersync  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "The Envio HyperSync Python client is not installed. Run `uv sync --extra dev` "
            "with HouseEdge v0.2.0 or install `hypersync>=1.2.0`."
        ) from exc
    return hypersync


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _as_int(value: Any) -> int:
    if value is None:
        raise ValueError("missing integer field in HyperSync response")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return int.from_bytes(bytes(value), "big")
    try:
        return int(value)
    except Exception as exc:  # pragma: no cover - defensive for future client wrappers
        text = str(value)
        return int(text, 16) if text.startswith("0x") else int(text)


def _as_hex(value: Any, *, size_bytes: int | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith("0x"):
            text = "0x" + text[2:]
        else:
            text = "0x" + text
    elif isinstance(value, (bytes, bytearray, memoryview)):
        text = "0x" + bytes(value).hex()
    elif hasattr(value, "hex"):
        text = value.hex()
        if not str(text).startswith("0x"):
            text = "0x" + str(text)
    else:
        n = int(value)
        width = 2 * size_bytes if size_bytes else max(2, (n.bit_length() + 7) // 8 * 2)
        text = "0x" + format(n, f"0{width}x")
    if size_bytes is not None:
        body = text[2:]
        if len(body) > size_bytes * 2:
            raise ValueError(f"hex value exceeds {size_bytes} bytes")
        text = "0x" + body.rjust(size_bytes * 2, "0")
    return text.lower()


def event_topic0(event_abi: dict) -> str:
    from web3 import Web3
    signature = f"{event_abi['name']}({','.join(i['type'] for i in event_abi['inputs'])})"
    # HexBytes.hex() has changed behavior across dependency versions: some
    # releases return a bare hex string while HyperSync requires 0x-prefixed
    # Ethereum hex values. Normalize explicitly at the adapter boundary.
    return _as_hex(Web3.keccak(text=signature), size_bytes=32)  # type: ignore[return-value]


def indexed_address_topic(address: str) -> str:
    from web3 import Web3
    body = Web3.to_checksum_address(address)[2:].lower()
    return "0x" + body.rjust(64, "0")


def _raw_log_to_dict(log: Any, timestamp_by_block: dict[int, pd.Timestamp]) -> dict:
    from hexbytes import HexBytes
    from web3 import Web3
    explicit_topics = [
        _get(log, "topic0", "topic_0"),
        _get(log, "topic1", "topic_1"),
        _get(log, "topic2", "topic_2"),
        _get(log, "topic3", "topic_3"),
    ]
    if any(t is not None for t in explicit_topics):
        topics_value = explicit_topics
    else:
        topics_value = _get(log, "topics", default=None) or []
        if isinstance(topics_value, str):
            raise ValueError("Unexpected scalar HyperSync `topics` value; request topic0..topic3 fields")
    topics = [_as_hex(t, size_bytes=32) for t in topics_value if t is not None]
    block_number = _as_int(_get(log, "block_number", "blockNumber"))
    tx_hash = _as_hex(_get(log, "transaction_hash", "transactionHash"), size_bytes=32)
    block_hash = _as_hex(_get(log, "block_hash", "blockHash"), size_bytes=32)
    address = _as_hex(_get(log, "address"), size_bytes=20)
    data = _as_hex(_get(log, "data")) or "0x"
    if block_number not in timestamp_by_block:
        raise RuntimeError(f"HyperSync response omitted timestamp for joined block {block_number}")
    return {
        "address": Web3.to_checksum_address(address),
        "topics": [HexBytes(t) for t in topics],
        "data": HexBytes(data),
        "blockNumber": block_number,
        "transactionHash": HexBytes(tx_hash or ("0x" + "00" * 32)),
        "transactionIndex": _as_int(_get(log, "transaction_index", "transactionIndex", default=0)),
        "blockHash": HexBytes(block_hash or ("0x" + "00" * 32)),
        "logIndex": _as_int(_get(log, "log_index", "logIndex")),
        "removed": bool(_get(log, "removed", default=False)),
        "timestamp": timestamp_by_block[block_number],
    }


async def _stream_raw_logs_async(
    *,
    address: str,
    topic_filters: list[list[str]],
    from_block: int,
    to_block: int,
    settings: HyperSyncSettings,
) -> list[dict]:
    """Fetch an inclusive block range from HyperSync with joined block timestamps."""
    hypersync = _hypersync_module()
    token = settings.token()
    client = hypersync.HypersyncClient(
        hypersync.ClientConfig(url=settings.url, bearer_token=token)
    )
    normalized_address = _as_hex(address, size_bytes=20)
    normalized_topics = [
        [_as_hex(topic, size_bytes=32) for topic in alternatives]
        for alternatives in topic_filters
    ]
    query = hypersync.Query(
        from_block=int(from_block),
        # HyperSync `to_block` is exclusive; HouseEdge ranges are inclusive.
        to_block=int(to_block) + 1,
        logs=[
            hypersync.LogSelection(
                address=[normalized_address],
                topics=normalized_topics,
            )
        ],
        field_selection=hypersync.FieldSelection(
            block=[hypersync.BlockField.NUMBER, hypersync.BlockField.TIMESTAMP],
            log=[
                hypersync.LogField.BLOCK_NUMBER,
                hypersync.LogField.LOG_INDEX,
                hypersync.LogField.TRANSACTION_INDEX,
                hypersync.LogField.TRANSACTION_HASH,
                hypersync.LogField.BLOCK_HASH,
                hypersync.LogField.DATA,
                hypersync.LogField.ADDRESS,
                hypersync.LogField.TOPIC0,
                hypersync.LogField.TOPIC1,
                hypersync.LogField.TOPIC2,
                hypersync.LogField.TOPIC3,
            ],
        ),
    )
    receiver = await client.stream(query, hypersync.StreamConfig())
    out: list[dict] = []
    while True:
        response = await receiver.recv()
        if response is None:
            break
        timestamp_by_block: dict[int, pd.Timestamp] = {}
        for block in response.data.blocks:
            number = _as_int(_get(block, "number", "block_number", "blockNumber"))
            timestamp = _as_int(_get(block, "timestamp"))
            timestamp_by_block[number] = pd.Timestamp(timestamp, unit="s", tz="UTC")
        for log in response.data.logs:
            out.append(_raw_log_to_dict(log, timestamp_by_block))
    out.sort(key=lambda r: (r["blockNumber"], r["transactionIndex"], r["logIndex"]))
    return out


def fetch_raw_logs(
    *,
    address: str,
    topic_filters: list[list[str]],
    from_block: int,
    to_block: int,
    settings: HyperSyncSettings,
) -> list[dict]:
    if int(to_block) < int(from_block):
        return []
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _stream_raw_logs_async(
                address=address,
                topic_filters=topic_filters,
                from_block=from_block,
                to_block=to_block,
                settings=settings,
            )
        )
    raise RuntimeError("HouseEdge synchronous HyperSync fetch cannot run inside an active asyncio loop")


async def _preflight_async(settings: HyperSyncSettings) -> dict:
    hypersync = _hypersync_module()
    client = hypersync.HypersyncClient(
        hypersync.ClientConfig(url=settings.url, bearer_token=settings.token())
    )
    chain_id = int(await client.get_chain_id())
    if chain_id != int(settings.require_chain_id):
        raise RuntimeError(
            f"Expected HyperSync chain id {settings.require_chain_id}; got {chain_id}"
        )
    # get_height exists on the current Python client; if a future client removes it,
    # chain-id validation remains sufficient and height is reported as None.
    height = None
    get_height = getattr(client, "get_height", None)
    if get_height is not None:
        height = int(await get_height())
    return {"url": settings.url, "chain_id": chain_id, "archive_height": height, "ok": True}


def preflight(settings: HyperSyncSettings) -> dict:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_preflight_async(settings))
    raise RuntimeError("HouseEdge synchronous HyperSync preflight cannot run inside an active asyncio loop")


def decode_event(log: dict, event_abi: dict) -> Any:
    """Decode one normalized HyperSync raw log using Web3's ABI decoder."""
    from web3 import Web3
    from web3._utils.events import get_event_data
    entry = {k: v for k, v in log.items() if k != "timestamp"}
    return get_event_data(Web3().codec, event_abi, entry)


def fetch_uniswap_v3_events(
    pool_address: str,
    spec,
    from_block: int,
    to_block: int,
    *,
    settings: HyperSyncSettings,
) -> pd.DataFrame:
    """Fetch and decode Swap/Mint/Burn/SetFeeProtocol with block timestamps."""
    from houseedge.data.uniswap_base import POOL_ABI, _event_rows

    event_abis = {
        abi["name"]: abi
        for abi in POOL_ABI
        if abi.get("type") == "event" and abi.get("name") in {"Swap", "Mint", "Burn", "SetFeeProtocol"}
    }
    from hexbytes import HexBytes
    topic_to_name = {event_topic0(abi): name for name, abi in event_abis.items()}
    raw = fetch_raw_logs(
        address=pool_address,
        topic_filters=[list(topic_to_name.keys())],
        from_block=from_block,
        to_block=to_block,
        settings=settings,
    )
    rows: list[dict] = []
    for item in raw:
        topic0 = _as_hex(item["topics"][0], size_bytes=32)
        name = topic_to_name.get(topic0)
        if name is None:
            continue
        decoded = decode_event(item, event_abis[name])
        row = _event_rows([decoded], name, spec)[0]
        row["timestamp"] = item["timestamp"]
        row["historical_source"] = "envio_hypersync"
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["block_number", "transaction_index", "log_index"]).reset_index(drop=True)
    return out


def fetch_decoded_event_logs(
    *,
    address: str,
    event_abi: dict,
    from_block: int,
    to_block: int,
    settings: HyperSyncSettings,
    indexed_topic_filters: Iterable[list[str]] = (),
) -> list[tuple[Any, pd.Timestamp]]:
    filters = [[event_topic0(event_abi)], *list(indexed_topic_filters)]
    raw = fetch_raw_logs(
        address=address,
        topic_filters=filters,
        from_block=from_block,
        to_block=to_block,
        settings=settings,
    )
    return [(decode_event(item, event_abi), item["timestamp"]) for item in raw]
