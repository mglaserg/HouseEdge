from __future__ import annotations

import numpy as np
import pandas as pd


def _future_mid(reference: pd.DataFrame, targets: pd.Series, tolerance_seconds: float) -> np.ndarray:
    r=reference[["timestamp","mid"]].copy().sort_values("timestamp")
    r["timestamp"]=pd.to_datetime(r["timestamp"],utc=True)
    t=pd.DataFrame({"target":pd.to_datetime(targets,utc=True)}).sort_values("target")
    m=pd.merge_asof(t,r.rename(columns={"timestamp":"ref_ts","mid":"future_mid"}),left_on="target",right_on="ref_ts",direction="nearest",tolerance=pd.to_timedelta(tolerance_seconds,unit="s"))
    return m.sort_index()["future_mid"].to_numpy()


def compute_markouts(aligned_swaps: pd.DataFrame, reference: pd.DataFrame, horizons_seconds: list[int], future_tolerance_seconds: float = 3.0) -> pd.DataFrame:
    x=aligned_swaps.copy()
    x=x[x["ref_mid"].notna()].copy()
    if x.empty:
        return x
    x["trader_direction"]=np.where(x["amount0"]<0,1.0,-1.0)
    # Effective execution price in token1 per token0 from actual pool token deltas.
    x["exec_price"]=np.where(x["amount0"]<0, x["amount1"]/(-x["amount0"]), (-x["amount1"])/x["amount0"])
    x["exec_edge_bps"]=x["trader_direction"]*(x["ref_mid"]-x["exec_price"])/x["exec_price"]*1e4
    for h in horizons_seconds:
        future=_future_mid(reference,x["timestamp"]+pd.to_timedelta(h,unit="s"),future_tolerance_seconds)
        x[f"future_mid_{h}s"]=future
        x[f"info_markout_{h}s_bps"]=x["trader_direction"]*(future/x["ref_mid"]-1.0)*1e4
        x[f"execution_markout_{h}s_bps"]=x["trader_direction"]*(future/x["exec_price"]-1.0)*1e4
    return x


def shuffled_direction_null(markouts: pd.DataFrame, horizons_seconds: list[int], reps: int = 1000, seed: int = 7) -> pd.DataFrame:
    rng=np.random.default_rng(seed)
    rows=[]
    d=markouts["trader_direction"].to_numpy(float)
    current=markouts["ref_mid"].to_numpy(float)
    for h in horizons_seconds:
        future=markouts[f"future_mid_{h}s"].to_numpy(float)
        valid=np.isfinite(future)&np.isfinite(current)&(current>0)
        vals=[]
        for _ in range(reps):
            ds=rng.permutation(d)
            vals.append(np.nanmean(ds[valid]*(future[valid]/current[valid]-1)*1e4))
        vals=np.asarray(vals)
        rows.append({"horizon_seconds":h,"null_mean_bps":float(np.nanmean(vals)),"null_p2_5_bps":float(np.nanquantile(vals,0.025)),"null_p97_5_bps":float(np.nanquantile(vals,0.975))})
    return pd.DataFrame(rows)
