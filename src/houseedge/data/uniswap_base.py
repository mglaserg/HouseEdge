from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import pandas as pd
from web3 import Web3

from houseedge.config import PoolSpec
from houseedge.data.storage import write_frame

FACTORY_ABI = [
    {"inputs":[{"internalType":"address","name":"tokenA","type":"address"},{"internalType":"address","name":"tokenB","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"}],"name":"getPool","outputs":[{"internalType":"address","name":"pool","type":"address"}],"stateMutability":"view","type":"function"}
]
POOL_ABI = [
    {"anonymous":False,"inputs":[{"indexed":True,"internalType":"address","name":"sender","type":"address"},{"indexed":True,"internalType":"address","name":"recipient","type":"address"},{"indexed":False,"internalType":"int256","name":"amount0","type":"int256"},{"indexed":False,"internalType":"int256","name":"amount1","type":"int256"},{"indexed":False,"internalType":"uint160","name":"sqrtPriceX96","type":"uint160"},{"indexed":False,"internalType":"uint128","name":"liquidity","type":"uint128"},{"indexed":False,"internalType":"int24","name":"tick","type":"int24"}],"name":"Swap","type":"event"},
    {"anonymous":False,"inputs":[{"indexed":False,"internalType":"address","name":"sender","type":"address"},{"indexed":True,"internalType":"address","name":"owner","type":"address"},{"indexed":True,"internalType":"int24","name":"tickLower","type":"int24"},{"indexed":True,"internalType":"int24","name":"tickUpper","type":"int24"},{"indexed":False,"internalType":"uint128","name":"amount","type":"uint128"},{"indexed":False,"internalType":"uint256","name":"amount0","type":"uint256"},{"indexed":False,"internalType":"uint256","name":"amount1","type":"uint256"}],"name":"Mint","type":"event"},
    {"anonymous":False,"inputs":[{"indexed":True,"internalType":"address","name":"owner","type":"address"},{"indexed":True,"internalType":"int24","name":"tickLower","type":"int24"},{"indexed":True,"internalType":"int24","name":"tickUpper","type":"int24"},{"indexed":False,"internalType":"uint128","name":"amount","type":"uint128"},{"indexed":False,"internalType":"uint256","name":"amount0","type":"uint256"},{"indexed":False,"internalType":"uint256","name":"amount1","type":"uint256"}],"name":"Burn","type":"event"},
    {"inputs":[],"name":"liquidity","outputs":[{"internalType":"uint128","name":"","type":"uint128"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"slot0","outputs":[{"internalType":"uint160","name":"sqrtPriceX96","type":"uint160"},{"internalType":"int24","name":"tick","type":"int24"},{"internalType":"uint16","name":"observationIndex","type":"uint16"},{"internalType":"uint16","name":"observationCardinality","type":"uint16"},{"internalType":"uint16","name":"observationCardinalityNext","type":"uint16"},{"internalType":"uint8","name":"feeProtocol","type":"uint8"},{"internalType":"bool","name":"unlocked","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"fee","outputs":[{"internalType":"uint24","name":"","type":"uint24"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}
]


def connect(rpc_url: str | None = None) -> Web3:
    url = rpc_url or os.environ.get("BASE_RPC_URL") or "https://mainnet.base.org"
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to Base RPC: {url}")
    if w3.eth.chain_id != 8453:
        raise RuntimeError(f"Expected Base chain id 8453; got {w3.eth.chain_id}")
    return w3


def discover_pool(w3: Web3, factory_address: str, spec: PoolSpec) -> str:
    factory = w3.eth.contract(address=Web3.to_checksum_address(factory_address), abi=FACTORY_ABI)
    addr = factory.functions.getPool(
        Web3.to_checksum_address(spec.token0_address),
        Web3.to_checksum_address(spec.token1_address),
        int(spec.fee_tier_pips),
    ).call()
    if int(addr, 16) == 0:
        raise RuntimeError("No pool found for configured tokens/fee tier")
    return Web3.to_checksum_address(addr)


def _block_timestamp(w3: Web3, block_number: int) -> tuple[int, pd.Timestamp]:
    b = w3.eth.get_block(block_number)
    return block_number, pd.Timestamp(int(b["timestamp"]), unit="s", tz="UTC")


def _attach_block_timestamps(w3: Web3, rows: list[dict], workers: int = 12) -> list[dict]:
    blocks = sorted({int(r["block_number"]) for r in rows})
    ts = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(_block_timestamp, w3, b): b for b in blocks}
        for fut in as_completed(futs):
            b, t = fut.result()
            ts[b] = t
    for r in rows:
        r["timestamp"] = ts[int(r["block_number"])]
    return rows


def _event_rows(event_logs: Iterable, event_name: str, spec: PoolSpec) -> list[dict]:
    rows=[]
    for ev in event_logs:
        a=dict(ev["args"])
        row={
            "event": event_name,
            "block_number": int(ev["blockNumber"]),
            "transaction_index": int(ev.get("transactionIndex", 0)),
            "log_index": int(ev["logIndex"]),
            "tx_hash": ev["transactionHash"].hex(),
        }
        if event_name == "Swap":
            row.update({
                "sender": a["sender"], "recipient": a["recipient"],
                "amount0_raw": int(a["amount0"]), "amount1_raw": int(a["amount1"]),
                "amount0": int(a["amount0"]) / 10**spec.token0_decimals,
                "amount1": int(a["amount1"]) / 10**spec.token1_decimals,
                "sqrt_price_x96": int(a["sqrtPriceX96"]),
                "liquidity": int(a["liquidity"]), "tick": int(a["tick"]),
            })
        else:
            row.update({
                "owner": a["owner"], "tick_lower": int(a["tickLower"]), "tick_upper": int(a["tickUpper"]),
                "liquidity_delta": int(a["amount"]) * (1 if event_name == "Mint" else -1),
                "amount0": int(a["amount0"]) / 10**spec.token0_decimals,
                "amount1": int(a["amount1"]) / 10**spec.token1_decimals,
            })
        rows.append(row)
    return rows


def fetch_events(
    w3: Web3,
    pool_address: str,
    spec: PoolSpec,
    from_block: int,
    to_block: int,
    chunk_blocks: int = 20_000,
    workers: int = 12,
) -> pd.DataFrame:
    """Fetch Swap/Mint/Burn logs in exact block/log order.

    The public Base RPC is rate-limited. For month-scale pulls, use a provider with archive/log capacity.
    """
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=POOL_ABI)
    rows=[]
    for start in range(int(from_block), int(to_block)+1, int(chunk_blocks)):
        end=min(start+chunk_blocks-1, int(to_block))
        for name in ("Swap", "Mint", "Burn"):
            event=getattr(pool.events, name)
            logs=event().get_logs(from_block=start, to_block=end)
            rows.extend(_event_rows(logs, name, spec))
    rows=_attach_block_timestamps(w3, rows, workers=workers) if rows else []
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df.sort_values(["block_number","transaction_index","log_index"]).reset_index(drop=True)
    return df


def save_events(df: pd.DataFrame, path: str | Path) -> Path:
    return write_frame(df, path)
