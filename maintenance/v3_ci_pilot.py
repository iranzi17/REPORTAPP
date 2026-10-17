"""CI-only disposable integration test of the REAL snapshot, no deployments."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from maintenance.v3_core import Manager, REPO, atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    data = Path(args.archive).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory(prefix="reportapp-v3-ci-") as folder:
        manager = Manager(Path(folder) / "separate-localappdata")
        atomic_json(manager.policy, {
            "enabled": True, "repository": REPO,
            "approved_tag": args.tag, "approved_sha256": sha,
            "office_cutover_approved": False,
        })
        receipt = manager.stage(args.tag, data, sha)
        assert receipt["status"] == "STAGED_TESTED", receipt
        assert all(count > 0 for count in receipt["tests"].values())
        assert receipt.get("component_checks", {}).get("status") == "COMPATIBLE"
        assert manager.status()["active"] is None
        assert not manager.active.exists()
        print(json.dumps({
            "status": "CI_ISOLATED_STAGING_PASSED",
            "file_isolation": "separate temporary directory",
            "release": args.tag, "suite_counts": receipt["tests"],
            "component_compatibility": receipt["component_checks"],
            "production_activated": False,
            "REG_source_modified": False,
        }, indent=2))


if __name__ == "__main__":
    main()
