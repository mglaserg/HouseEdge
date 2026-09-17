from __future__ import annotations

import math
import time
import pandas as pd
from typing import Any, Callable

from houseedge.data.base_rpc import attach_block_timestamps, block_timestamp, get_event_logs_resilient

AAVE_V3_BASE_POOL = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"
AAVE_V3_BASE_DATA_PROVIDER = "0x0F43731EB8d45A581f4a36DD74F5f358bc90C73A"
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
RAY = 10**27
SECONDS_PER_YEAR = 365 * 24 * 60 * 60

POOL_ABI = [{
    "anonymous": False,
    "inputs": [
        {"indexed": True, "internalType": "address", "name": "reserve", "type": "address"},
        {"indexed": False, "internalType": "uint256", "name": "liquidityRate", "type": "uint256"},
        {"indexed": False, "internalType": "uint256", "name": "stableBorrowRate", "type": "uint256"},
        {"indexed": False, "internalType": "uint256", "name": "variableBorrowRate", "type": "uint256"},
        {"indexed": False, "internalType": "uint256", "name": "liquidityIndex", "type": "uint256"},
        {"indexed": False, "internalType": "uint256", "name": "variableBorrowIndex", "type": "uint256"},
    ],
    "name": "ReserveDataUpdated",
    "type": "event",
}]

DATA_PROVIDER_ABI = [{
    "inputs": [{"internalType":"address","name":"asset","type":"address"}],
    "name":"getReserveData",
    "outputs":[
        {"internalType":"uint256","name":"unbacked","type":"uint256"},
        {"internalType":"uint256","name":"accruedToTreasuryScaled","type":"uint256"},
        {"internalType":"uint256","name":"totalAToken","type":"uint256"},
        {"internalType":"uint256","name":"totalStableDebt","type":"uint256"},
        {"internalType":"uint256","name":"totalVariableDebt","type":"uint256"},
        {"internalType":"uint256","name":"liquidityRate","type":"uint256"},
        {"internalType":"uint256","name":"variableBorrowRate","type":"uint256"},
        {"internalType":"uint256","name":"stableBorrowRate","type":"uint256"},
        {"internalType":"uint256","name":"averageStableBorrowRate","type":"uint256"},
        {"internalType":"uint256","name":"liquidityIndex","type":"uint256"},
        {"internalType":"uint256","name":"variableBorrowIndex","type":"uint256"},
        {"internalType":"uint40","name":"lastUpdateTimestamp","type":"uint40"},
    ],
    "stateMutability":"view","type":"function"
}]


def ray_apr_to_apy(liquidity_rate_ray: int | float) -> float:
    apr = float(liquidity_rate_ray) / RAY
    return math.expm1(SECONDS_PER_YEAR * math.log1p(apr / SECONDS_PER_YEAR))


def fetch_usdc_supply_rates(
    w3: Any,
    from_block: int,
    to_block: int,
    *,
    asset: str = BASE_USDC,
    pool_address: str = AAVE_V3_BASE_POOL,
    data_provider_address: str = AAVE_V3_BASE_DATA_PROVIDER,
    chunk_blocks: int = 20_000,
    workers: int = 12,
) -> pd.DataFrame:
    """Reconstruct Aave Base USDC supply APY from on-chain ReserveDataUpdated events."""
    from web3 import Web3
    asset = Web3.to_checksum_address(asset)
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=POOL_ABI)
    provider = w3.eth.contract(address=Web3.to_checksum_address(data_provider_address), abi=DATA_PROVIDER_ABI)
    initial_block = max(0, int(from_block) - 1)
    reserve_data = provider.functions.getReserveData(asset).call(block_identifier=initial_block)
    initial_rate = int(reserve_data[5])
    rows = [{
        "block_number": initial_block,
        "transaction_index": -1,
        "log_index": -1,
        "liquidity_rate_ray": initial_rate,
        "source": "aave_v3_base_onchain_initial",
    }]
    event = pool.events.ReserveDataUpdated
    for start in range(int(from_block), int(to_block) + 1, int(chunk_blocks)):
        end = min(start + int(chunk_blocks) - 1, int(to_block))
        logs = get_event_logs_resilient(event, from_block=start, to_block=end, argument_filters={"reserve": asset})
        for ev in logs:
            args = ev["args"]
            rows.append({
                "block_number": int(ev["blockNumber"]),
                "transaction_index": int(ev.get("transactionIndex", 0)),
                "log_index": int(ev["logIndex"]),
                "liquidity_rate_ray": int(args["liquidityRate"]),
                "source": "aave_v3_base_ReserveDataUpdated",
            })
    rows = attach_block_timestamps(w3, rows, workers=workers)
    out = pd.DataFrame(rows).sort_values(["block_number","transaction_index","log_index"]).reset_index(drop=True)
    out["apy"] = out["liquidity_rate_ray"].map(ray_apr_to_apy)
    return out[["timestamp","apy","liquidity_rate_ray","block_number","source"]]



def fetch_usdc_supply_rates_hypersync(
    w3: Any,
    from_block: int,
    to_block: int,
    *,
    settings,
    asset: str = BASE_USDC,
    pool_address: str = AAVE_V3_BASE_POOL,
    data_provider_address: str = AAVE_V3_BASE_DATA_PROVIDER,
    chunk_blocks: int = 100_000,
    max_retries: int = 4,
    retry_base_seconds: float = 1.0,
    emit: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Reconstruct Base USDC supply APY using HyperSync for bulk rate-update logs.

    RPC is used only once for the initial historical reserve state immediately
    before the window. This avoids the provider's eth_getLogs range limits.
    """
    from web3 import Web3
    from houseedge.data.hypersync_base import fetch_decoded_event_logs, indexed_address_topic

    asset = Web3.to_checksum_address(asset)
    provider = w3.eth.contract(address=Web3.to_checksum_address(data_provider_address), abi=DATA_PROVIDER_ABI)
    initial_block = max(0, int(from_block) - 1)
    reserve_data = provider.functions.getReserveData(asset).call(block_identifier=initial_block)
    rows = [{
        "timestamp": block_timestamp(w3, initial_block),
        "block_number": initial_block,
        "transaction_index": -1,
        "log_index": -1,
        "liquidity_rate_ray": int(reserve_data[5]),
        "source": "aave_v3_base_onchain_initial_rpc_state",
    }]
    event_abi = POOL_ABI[0]
    chunk_blocks = max(1, int(chunk_blocks))
    max_retries = max(0, int(max_retries))
    for start in range(int(from_block), int(to_block) + 1, chunk_blocks):
        end = min(start + chunk_blocks - 1, int(to_block))
        decoded = None
        for attempt in range(max_retries + 1):
            try:
                if emit is not None:
                    emit(
                        f"Aave HyperSync blocks {start:,}-{end:,}"
                        + (f" retry {attempt}/{max_retries}" if attempt else "")
                    )
                decoded = fetch_decoded_event_logs(
                    address=pool_address,
                    event_abi=event_abi,
                    from_block=start,
                    to_block=end,
                    settings=settings,
                    indexed_topic_filters=[[indexed_address_topic(asset)]],
                )
                break
            except Exception as exc:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"Aave HyperSync chunk failed after {max_retries + 1} attempts "
                        f"for blocks {start}-{end}: {exc}"
                    ) from exc
                delay = float(retry_base_seconds) * (2 ** attempt)
                if emit is not None:
                    emit(
                        f"Aave HyperSync transport failure for blocks {start:,}-{end:,}; "
                        f"retrying in {delay:.1f}s: {exc}"
                    )
                time.sleep(delay)
        assert decoded is not None
        for ev, timestamp in decoded:
            args = ev["args"]
            rows.append({
                "timestamp": timestamp,
                "block_number": int(ev["blockNumber"]),
                "transaction_index": int(ev.get("transactionIndex", 0)),
                "log_index": int(ev["logIndex"]),
                "liquidity_rate_ray": int(args["liquidityRate"]),
                "source": "aave_v3_base_ReserveDataUpdated_hypersync",
            })
    out = pd.DataFrame(rows).sort_values(["block_number", "transaction_index", "log_index"]).reset_index(drop=True)
    out["apy"] = out["liquidity_rate_ray"].map(ray_apr_to_apy)
    return out[["timestamp", "apy", "liquidity_rate_ray", "block_number", "source"]]
