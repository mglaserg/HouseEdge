from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env", *, override: bool = False) -> Path | None:
    """Load simple KEY=VALUE pairs from a local .env file.

    This is intentionally dependency-free. Blank lines and comments are ignored;
    optional ``export`` prefixes and matching single/double quotes are supported.
    Existing environment variables win unless ``override=True``.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path
