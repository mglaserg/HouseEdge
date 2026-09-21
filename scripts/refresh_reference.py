from __future__ import annotations

import argparse
import json

from houseedge.data.fair_value import rebuild_multi_venue_references


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Select the reference policy on calibration, rebuild calibration and "
            "candidate references, and report the fixed coverage gate."
        )
    )
    parser.add_argument("--config", default="configs/experiment_001.yaml")
    parser.add_argument("--output-root", default="data")
    parser.add_argument("--force-downloads", action="store_true")
    parser.add_argument("--report", default="runs/v015_reference_feasibility.json")
    parser.add_argument("--no-apply-selection", action="store_true")
    args = parser.parse_args()

    result = rebuild_multi_venue_references(
        config_path=args.config,
        output_root=args.output_root,
        report_path=args.report,
        force_downloads=args.force_downloads,
        apply_selection=not args.no_apply_selection,
        progress=lambda msg: print(f"• {msg}", flush=True),
    )
    print(json.dumps(result, indent=2))
    if result.get("status") != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
