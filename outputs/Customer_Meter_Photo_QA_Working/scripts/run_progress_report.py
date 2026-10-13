"""Command-line runner for the ArcGIS LV survey progress report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from meter_photo_qa.progress_report import generate_progress_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_xlsx")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--user", action="append", required=True, dest="users")
    parser.add_argument("--district")
    parser.add_argument("--sector", action="append", default=[], dest="sectors")
    args = parser.parse_args()
    summary = generate_progress_report(
        output_xlsx=args.output_xlsx,
        start_date=args.start,
        end_date=args.end,
        usernames=args.users,
        district=args.district,
        sectors=args.sectors,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
