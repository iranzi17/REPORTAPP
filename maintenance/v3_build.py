"""Build an immutable V3 candidate snapshot. Never publish or install implicitly."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from maintenance.v3_core import (
    AGENT_VERSION, REPO, REQUIRED_FILES, WORK_REL, expected_test_names,
    MAX_ARCHIVE, MAX_ENTRY, MAX_UNPACKED, safe_name, safe_path,
)


def build(tag, root, destination):
    safe_name(tag)
    root = Path(root).resolve()
    work = root / WORK_REL
    paths = []
    for folder, pattern in ((work / "src" / "meter_photo_qa", "*.py"),
                            (work / "tests", "test_*.py")):
        if not folder.is_dir():
            raise ValueError("Mandatory release source folder missing")
        paths.extend(p for p in folder.rglob(pattern) if p.is_file())
    for relative in ("config/lv_line_quality_rules.json",
                     "config/report_user_names.json",
                     "config/rwanda_district_sectors.json"):
        if (work / relative).is_file():
            paths.append(work / relative)
    reference = work / "addins" / "ReportappNavigationBridge" / "BridgeModule.cs"
    if not reference.is_file():
        raise ValueError("Missing immutable navigation source for regression tests")
    paths.append(reference)
    files = {}
    total = 0
    for path in sorted(set(paths)):
        if path.is_symlink():
            raise ValueError("Symlink not allowed")
        relative = path.relative_to(root).as_posix()
        if not safe_path(relative):
            raise ValueError("Forbidden release entry: " + relative)
        data = path.read_bytes()
        total += len(data)
        if len(data) > MAX_ENTRY or total > MAX_UNPACKED:
            raise ValueError("Release file or expansion size exceeds limit")
        if relative.endswith(".py"):
            compile(data, relative, "exec")
        files[relative] = data
    if not REQUIRED_FILES.issubset(files):
        raise ValueError("Mandatory application file or test missing")
    all_required_tests = expected_test_names(files)
    for name in all_required_tests:
        if f"{WORK_REL}/tests/{name}" not in files:
            raise ValueError("Mandatory regression test absent: " + name)
    manifest = {
        "format": 3,
        "repository": REPO,
        "tag": tag,
        "min_agent_version": AGENT_VERSION,
        "python": "3.11",
        "arcgis_pro": "3.4",
        "component_versions": {
            "navigation_bridge_required": "1.0.4",
            "deployment_layout": "versioned-pointer",
        },
        "required_tests": list(all_required_tests),
        "files": {name: hashlib.sha256(value).hexdigest()
                  for name, value in sorted(files.items())},
    }
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
        for name, value in sorted(files.items()):
            archive.writestr(name, value)
    if destination.stat().st_size > MAX_ARCHIVE:
        destination.unlink(missing_ok=True)
        raise ValueError("Compressed release size exceeds limit")
    return {"file": str(destination), "tag": tag,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "file_count": len(files)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.tag, args.root, args.output), indent=2))


if __name__ == "__main__":
    main()
