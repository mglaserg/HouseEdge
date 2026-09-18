from __future__ import annotations

import argparse
import json

from houseedge.config import load_yaml
from houseedge.data.acquire import refresh_binance_references


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild only the Binance calibration/candidate reference files "
            "from existing HouseEdge event datasets."
        )
    )
    parser.add_argument("--config", default="configs/experiment_001.yaml")
    parser.add_argument("--output-root", default="data")
    parser.add_argument("--force-downloads", action="store_true")
    parser.add_argument("--window", choices=("calibration", "candidate", "both"), default="calibration")
    args = parser.parse_args()

    cfg = load_yaml(args.config)
    windows = ("calibration", "candidate") if args.window == "both" else (args.window,)
    result = refresh_binance_references(
        cfg,
        output_root=args.output_root,
        force_downloads=args.force_downloads,
        windows=windows,
        progress=lambda msg: print(f"• {msg}", flush=True),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
