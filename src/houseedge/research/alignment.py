from __future__ import annotations

import numpy as np
import pandas as pd


def align_reference(swaps: pd.DataFrame, reference: pd.DataFrame, tolerance_seconds: float = 3.0, shift_seconds: float = 0.0) -> pd.DataFrame:
    s=swaps.copy().sort_values("timestamp")
    r=reference.copy().sort_values("timestamp")
    s["timestamp"]=pd.to_datetime(s["timestamp"], utc=True)
    r["timestamp"]=pd.to_datetime(r["timestamp"], utc=True)+pd.to_timedelta(shift_seconds, unit="s")
    r=r.rename(columns={"timestamp":"quote_timestamp","mid":"ref_mid"})
    keep=[c for c in ["quote_timestamp","ref_mid","bid","ask","source"] if c in r]
    out=pd.merge_asof(s, r[keep].sort_values("quote_timestamp"), left_on="timestamp", right_on="quote_timestamp", direction="nearest", tolerance=pd.to_timedelta(tolerance_seconds,unit="s"))
    out["quote_age_seconds"]=(out["timestamp"]-out["quote_timestamp"]).dt.total_seconds().abs()
    return out


def alignment_sensitivity(swaps: pd.DataFrame, reference: pd.DataFrame, shifts_seconds: list[float], tolerance_seconds: float) -> pd.DataFrame:
    rows=[]
    for shift in shifts_seconds:
        a=align_reference(swaps,reference,tolerance_seconds=tolerance_seconds,shift_seconds=shift)
        matched=a["ref_mid"].notna()
        # Pool amount0 sign determines trader base direction when token0 is the base asset.
        direction=np.where(a["amount0"]<0,1.0,-1.0)
        info=np.where(matched, direction*(a["ref_mid"].pct_change().fillna(0))*1e4, np.nan)
        rows.append({"shift_seconds":shift,"match_rate":float(matched.mean()),"median_quote_age_seconds":float(a.loc[matched,"quote_age_seconds"].median()) if matched.any() else np.nan,"rough_signed_step_bps":float(np.nanmean(info))})
    return pd.DataFrame(rows)
