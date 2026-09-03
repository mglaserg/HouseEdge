from __future__ import annotations
import numpy as np
import pandas as pd
from houseedge.amm.v3_math import price_to_tick


def synthetic_tape(n: int = 5000, seed: int = 42) -> tuple[pd.DataFrame,pd.DataFrame]:
    """Synthetic swap + reference tape for plumbing validation only."""
    rng=np.random.default_rng(seed)
    start=pd.Timestamp("2026-08-01T00:00:00Z")
    # Irregular quote tape every second.
    sec=np.arange(0, 3*24*3600, 1)
    sigma_sec=0.55/np.sqrt(365*24*3600)
    logp=np.log(3500.0)+np.cumsum(rng.normal(0,sigma_sec,len(sec)))
    mid=np.exp(logp)
    ref=pd.DataFrame({"timestamp":start+pd.to_timedelta(sec,unit="s"),"mid":mid,"source":"synthetic"})
    # Sample swap seconds with clustering.
    swap_sec=np.sort(rng.choice(sec[5:-310],size=n,replace=False))
    p=np.interp(swap_sec,sec,mid)
    informed=rng.normal(0,1,n)
    direction=np.where(informed>0,1,-1)
    # Give trader direction a tiny relation to next return so markouts are nonzero.
    future=np.interp(swap_sec+60,sec,mid)
    direction=np.where((future/p-1)+rng.normal(0,0.0007,n)>0,1,-1)
    size_usd=np.exp(rng.normal(np.log(8000),1.0,n)).clip(200,300000)
    fee=0.0005
    # Positive amount0 = trader sold token0; negative = trader bought token0.
    base=size_usd/p
    amount0=np.where(direction>0,-base,base)
    amount1=np.where(direction>0,size_usd*(1+fee),-size_usd*(1-fee))
    ticks=[price_to_tick(float(px),18,6) for px in p]
    # Active liquidity roughly equivalent to a deep major pool in raw-L units.
    liquidity=np.full(n,2.5e20)
    sqrt_raw=np.sqrt(p/10**12)*(2**96)
    swaps=pd.DataFrame({
        "event":"Swap","timestamp":start+pd.to_timedelta(swap_sec,unit="s"),
        "block_number":swap_sec//2+1000000,"transaction_index":0,"log_index":np.arange(n),
        "amount0":amount0,"amount1":amount1,"sqrt_price_x96":sqrt_raw.astype(object),
        "liquidity":liquidity,"tick":ticks,
    })
    return swaps,ref
