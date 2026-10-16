"""Build an explicitly allowlisted REPORTAPP safe update archive.

Run only in the reviewed GitHub Actions release workflow. The archive
contains approved QA watcher/Inbox Python files and regression tests only,
with hashes and no user data.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

REPO = "iranzi17/REPORTAPP"
TAG = re.compile(r"^reportapp-safe-v[0-9]{8}-[0-9]{3}$")
ALLOWED = (
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/notification_inbox.py",
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/surveyor_notifications.py",
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/surveyor_activity.py",
    "outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/deferred_notifications.py",
    "outputs/Customer_Meter_Photo_QA_Working/tests/test_deferred_notifications.py",
    "maintenance/self_monitor.py",
)


def build(tag, root, destination):
    if not TAG.fullmatch(tag):
        raise ValueError("Invalid approved release tag.")
    root = Path(root).resolve()
    destination = Path(destination)
    files = {}
    for rel in ALLOWED:
        path = (root / rel).resolve()
        if root not in path.parents or path.is_symlink() or not path.is_file():
            raise ValueError("Missing or unsafe deployment source: " + rel)
        data = path.read_bytes()
        if len(data) > 300000:
            raise ValueError("Safe Inbox UI file exceeds size limit.")
        compile(data, rel, "exec")
        files[rel] = (data, hashlib.sha256(data).hexdigest())
    manifest = {
        "format": 1,
        "repository": REPO,
        "tag": tag,
        "files": {rel: digest for rel, (_, digest) in files.items()},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
        for rel, (data, _) in files.items():
            z.writestr(rel, data)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="reportapp-safe-update.zip")
    options = parser.parse_args()
    print(build(options.tag, options.root, options.output))


if __name__ == "__main__":
    main()
