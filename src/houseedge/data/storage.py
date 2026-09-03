from __future__ import annotations
from pathlib import Path
import pandas as pd


def write_frame(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        df.to_csv(path, index=False)
    else:
        df.to_parquet(path, index=False)
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
