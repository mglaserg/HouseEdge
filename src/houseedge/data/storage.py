from __future__ import annotations
from pathlib import Path
import hashlib
import json
import os
import numbers
import pandas as pd

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def parquet_safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a Parquet-safe copy without losing arbitrary-precision EVM ints.

    Ethereum ABI values such as uint160/uint128/uint256 routinely exceed signed
    int64. pandas stores those as Python integers, but Arrow may attempt to pass
    them through a native C ``long`` while inferring a column type, raising
    ``OverflowError: Python int too large to convert to C long``.

    Any column containing an integer outside signed-int64 is serialized as a
    nullable decimal string. Downstream HouseEdge code already converts these
    fields explicitly with ``int(...)`` / ``float(...)`` when numeric use is
    required, so this keeps storage lossless and portable.
    """
    out = df.copy()
    for col in out.columns:
        s = out[col]
        wide = False
        if pd.api.types.is_unsigned_integer_dtype(s.dtype):
            # uint64 can exceed Arrow/native signed integer paths on some builds.
            try:
                wide = bool(len(s) and int(s.max()) > _INT64_MAX)
            except Exception:
                wide = True
        elif s.dtype == object:
            for value in s.dropna():
                if isinstance(value, numbers.Integral) and not isinstance(value, bool):
                    n = int(value)
                    if n < _INT64_MIN or n > _INT64_MAX:
                        wide = True
                        break
        if wide:
            out[col] = s.map(lambda v: None if pd.isna(v) else str(int(v)))
    return out


def write_frame(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        if path.suffix.lower() == ".csv":
            df.to_csv(tmp, index=False)
        else:
            parquet_safe_frame(df).to_parquet(tmp, index=False)
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
    if path.is_dir():
        parts = sorted(path.glob("part-*.parquet"))
        if not parts:
            df = pd.DataFrame()
        else:
            frames = [pd.read_parquet(part) for part in parts]
            df = pd.concat(frames, ignore_index=True, sort=False) if len(frames) > 1 else frames[0]
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_parquet(path)
    for c in ("timestamp", "quote_timestamp"):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True)
    return df


def read_dataset_columns(path: str | Path, columns: list[str]) -> pd.DataFrame:
    """Project a few columns from a file or partitioned dataset without loading full rows."""
    path = Path(path)
    if not path.is_dir():
        return pd.read_parquet(path, columns=columns)
    frames=[]
    for part in sorted(path.glob("part-*.parquet")):
        frames.append(pd.read_parquet(part, columns=columns))
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True, sort=False) if len(frames)>1 else frames[0]


def artifact_size(path: str | Path) -> int:
    """Return total bytes for a file or a partitioned dataset directory."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def artifact_sha256(path: str | Path) -> str:
    """Stable SHA-256 for a file or directory tree (relative paths + bytes)."""
    path = Path(path)
    h = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    if path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            rel = child.relative_to(path).as_posix().encode("utf-8")
            h.update(len(rel).to_bytes(4, "big")); h.update(rel)
            with child.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
        return h.hexdigest()
    raise FileNotFoundError(path)


def mark_dataset_complete(dataset_dir: str | Path, payload: dict) -> Path:
    dataset_dir = Path(dataset_dir).expanduser()
    dataset_dir.mkdir(parents=True, exist_ok=True)
    tmp = dataset_dir / "_SUCCESS.tmp"
    final = dataset_dir / "_SUCCESS.json"
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, final)
    return final


def dataset_complete(dataset_dir: str | Path) -> bool:
    return (Path(dataset_dir) / "_SUCCESS.json").exists()
