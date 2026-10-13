"""Run the read-only pilot preflight inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from meter_photo_qa.arcgis_inventory import run_inventory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--where", default="1=1")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "outputs" / "pilot_preflight.csv"))
    parser.add_argument("--service-url")
    args = parser.parse_args()
    print(json.dumps(run_inventory(args.output, args.limit, args.where, args.service_url), indent=2, default=str))


if __name__ == "__main__":
    main()

