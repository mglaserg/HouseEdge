from __future__ import annotations
from pathlib import Path
import os
import pandas as pd


def write_frame(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        if path.suffix.lower() == ".csv":
            df.to_csv(tmp, index=False)
        else:
            df.to_parquet(tmp, index=False)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"Writer produced no bytes for {path}")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Artifact was not materialized: {path}")
    return path


def read_frame(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_parquet(path)
    for c in ("timestamp", "quote_timestamp"):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True)
    return df
