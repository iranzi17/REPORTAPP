"""Create the ONE-TIME REPORTAPP v1-compatible Inbox-only bootstrap release.

The installed v1 maintenance agent permits *only* notification_inbox.py.
This release delivers the user-approved Upgrade button, without touching the
watcher or silently broadening the local updater.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import re
import zipfile

REPO="iranzi17/REPORTAPP"
REL="outputs/Customer_Meter_Photo_QA_Working/src/meter_photo_qa/notification_inbox.py"

def build(tag,root,output):
    if not re.fullmatch(r"reportapp-safe-v[0-9]{8}-[0-9]{3}",tag):
        raise ValueError("Unsafe bootstrap version tag.")
    root=Path(root).resolve()
    source=(root/REL).resolve()
    if root not in source.parents or not source.is_file():
        raise ValueError("Inbox UI source unavailable.")
    data=source.read_bytes()
    if len(data)>300000:
        raise ValueError("Inbox UI too large.")
    compile(data,REL,"exec")
    meta={"format":1,"repository":REPO,"tag":tag,
          "files":{REL:hashlib.sha256(data).hexdigest()}}
    target=Path(output)
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",json.dumps(meta,sort_keys=True))
        z.writestr(REL,data)
    return target

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--tag",required=True)
    parser.add_argument("--output",required=True)
    p=parser.parse_args()
    print(build(p.tag,Path(__file__).resolve().parents[1],p.output))
