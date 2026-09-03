from __future__ import annotations

import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import websockets

from houseedge.data.storage import write_frame

COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"


def normalize_reference(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize external reference data to timestamp, bid, ask, mid, source.

    Accepts either a `mid` column or bid+ask. Timestamp must be parseable UTC.
    """
    out=df.copy()
    if "timestamp" not in out:
        raise ValueError("reference data requires timestamp")
    out["timestamp"]=pd.to_datetime(out["timestamp"], utc=True)
    if "mid" not in out:
        if not {"bid","ask"}.issubset(out.columns):
            raise ValueError("reference data requires mid or bid+ask")
        out["mid"]=(pd.to_numeric(out["bid"])+pd.to_numeric(out["ask"]))/2
    out["mid"]=pd.to_numeric(out["mid"])
    if "source" not in out:
        out["source"]="external"
    return out.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)


async def collect_coinbase_ticker(product_id: str, seconds: int, output: str | Path) -> Path:
    """Prospectively collect public Coinbase ticker bid/ask updates."""
    rows=[]
    sub={"type":"subscribe","product_ids":[product_id],"channels":["ticker"]}
    deadline=asyncio.get_running_loop().time()+seconds
    async with websockets.connect(COINBASE_WS, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps(sub))
        while asyncio.get_running_loop().time() < deadline:
            timeout=max(0.1, deadline-asyncio.get_running_loop().time())
            try:
                msg=await asyncio.wait_for(ws.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                break
            obj=json.loads(msg)
            if obj.get("type") != "ticker":
                continue
            bid=obj.get("best_bid"); ask=obj.get("best_ask")
            if not bid or not ask:
                continue
            ts=pd.to_datetime(obj.get("time") or datetime.now(timezone.utc), utc=True)
            rows.append({"timestamp":ts,"bid":float(bid),"ask":float(ask),"mid":(float(bid)+float(ask))/2,"source":"coinbase","sequence":obj.get("sequence")})
    return write_frame(pd.DataFrame(rows), output)
