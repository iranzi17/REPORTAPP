"""Click-to-zoom request handler for REPORTAPP desktop notifications.

A Windows user explicitly registers the per-user reportapp:// URL protocol.
Clicking a toast only writes a validated request to a local queue. The
ArcGIS Pro SDK add-in handles map selections; this process NEVER edits REG
data or launches a second ArcGIS Pro instance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid
from urllib.parse import urlsplit

SCHEME="reportapp"
REGISTRATION_KEY=r"Software\Classes\reportapp"
ASSET_LAYER_IDS={"pole":12,"line":10,"transformer":7}
SERVICE_URL=("https://gisweb.reg.rw/server/rest/services/"
             "REGUN_Service__Versio2/FeatureServer")
MAX_OBJECTID=9223372036854775807


def queue_folder(env=None):
    env=os.environ if env is None else env
    base=env.get("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA missing; cannot queue Windows navigation.")
    return Path(base).expanduser().resolve()/"REPORTAPP"/"Navigation"/"Requests"


def zoom_uri(asset,objectid):
    asset=str(asset).strip().casefold()
    if asset not in ASSET_LAYER_IDS:
        raise ValueError("Unsupported REG asset type.")
    if isinstance(objectid,bool) or not re.fullmatch(r"[0-9]{1,19}",str(objectid)):
        raise ValueError("Invalid positive source OBJECTID.")
    try:
        oid=int(objectid)
    except (ValueError,TypeError,OverflowError) as exc:
        raise ValueError("Invalid positive source OBJECTID.") from exc
    if not 0<oid<=MAX_OBJECTID:
        raise ValueError("Invalid positive source OBJECTID.")
    return f"{SCHEME}://zoom/{asset}/{oid}"


def parse_uri(uri):
    supplied=str(uri or "").strip().strip('"')
    parts=urlsplit(supplied)
    if parts.scheme.casefold()!=SCHEME or parts.netloc.casefold()!="zoom":
        raise ValueError("Unsupported REPORTAPP navigation link.")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("Unexpected navigation link component.")
    match=re.fullmatch(r"/(pole|line|transformer)/([0-9]{1,19})",parts.path)
    if not match:
        raise ValueError("Navigation path must contain an asset and OBJECTID.")
    asset=match.group(1)
    oid=int(match.group(2))
    return asset,oid,zoom_uri(asset,oid)

def paused_flag(folder=None):
    requests=Path(folder).resolve() if folder is not None else queue_folder()
    return requests.parent/"navigation-paused.flag"


def is_navigation_paused(folder=None):
    return paused_flag(folder).exists()


def pause_navigation(folder=None):
    """Emergency stop: block new zoom requests and preserve pending old clicks."""
    requests=Path(folder).resolve() if folder is not None else queue_folder()
    requests.mkdir(parents=True,exist_ok=True)
    flag=paused_flag(requests)
    flag.write_text("REPORTAPP navigation paused by user.\n",encoding="utf-8")
    moved=0
    for item in requests.glob("*.json"):
        try:
            item.rename(item.with_name(item.name+".paused"))
            moved+=1
        except FileNotFoundError:
            # ArcGIS Pro consumed or renamed the request concurrently.
            continue
    return {"paused":True,"pending_requests_paused":moved}


def resume_navigation(folder=None):
    """Resume only NEW explicit zoom clicks; never replay old paused requests."""
    flag=paused_flag(folder)
    flag.unlink(missing_ok=True)
    return {"paused":False,"previous_requests_replayed":0}


def enqueue(uri,folder=None,now=None):
    asset,oid,canonical=parse_uri(uri)
    destination=Path(folder) if folder is not None else queue_folder()
    destination.mkdir(parents=True,exist_ok=True)
    if is_navigation_paused(destination):
        raise RuntimeError("REPORTAPP map navigation is paused; resume it in the Inbox first.")
    identity=uuid.uuid4().hex
    timestamp=int(now if now is not None
                  else datetime.now(timezone.utc).timestamp()*1000)
    request={
        "version":1,"request_id":identity,"asset":asset,"objectid":oid,
        "layer_id":ASSET_LAYER_IDS[asset],"service_url":SERVICE_URL,
        "created_utc_ms":timestamp,"origin":"REPORTAPP_NOTIFICATION",
    }
    temporary=destination/("."+identity+".tmp")
    final=destination/(identity+".json")
    try:
        with temporary.open("x",encoding="utf-8") as writer:
            json.dump(request,writer,ensure_ascii=False)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary,final)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"queue_file":str(final),"request":request,"uri":canonical}


def registry_command(executable=None):
    python=Path(executable or sys.executable).resolve()
    if python.name.casefold() not in ("python.exe","pythonw.exe"):
        raise ValueError("Use a standalone Python executable.")
    candidate=python.with_name("pythonw.exe")
    if candidate.is_file():
        python=candidate
    script=Path(__file__).resolve()
    return f'"{python}" "{script}" --uri "%1"'


def is_registered(winreg_module=None):
    if os.name!="nt" and winreg_module is None:
        return False
    if winreg_module is None:
        import winreg as winreg_module
    try:
        with winreg_module.OpenKey(
            winreg_module.HKEY_CURRENT_USER,REGISTRATION_KEY+r"\shell\open\command"
        ) as key:
            value,_=winreg_module.QueryValueEx(key,"")
        return "alert_navigation.py" in value and "--uri" in value
    except (FileNotFoundError,OSError):
        return False


def register_windows_protocol(winreg_module=None,python=None):
    """User-requested HKCU registration. No admin and no REG server writes."""
    if os.name!="nt" and winreg_module is None:
        raise RuntimeError("Windows desktop only.")
    if winreg_module is None:
        import winreg as winreg_module
    command=registry_command(python)
    for subkey,name,value in (
        (REGISTRATION_KEY,"","URL:REPORTAPP navigation"),
        (REGISTRATION_KEY,"URL Protocol",""),
        (REGISTRATION_KEY+r"\shell\open\command","",command),
    ):
        with winreg_module.CreateKey(winreg_module.HKEY_CURRENT_USER,subkey) as key:
            winreg_module.SetValueEx(key,name,0,winreg_module.REG_SZ,value)
    return command


def main(argv=None):
    parser=argparse.ArgumentParser(description="REPORTAPP ArcGIS Pro zoom-link handler")
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--register",action="store_true",
                        help="Register the reportapp:// URI for the current Windows user")
    action.add_argument("--status",action="store_true",
                        help="Show handler registration and queue location")
    action.add_argument("--uri",help="Validate and queue a clicked reportapp:// URL")
    args=parser.parse_args(argv)
    if args.register:
        print("Windows reportapp:// registered:",register_windows_protocol())
    elif args.status:
        print(json.dumps({"registered":is_registered(),
                          "queue":str(queue_folder())},indent=2))
    else:
        print(json.dumps(enqueue(args.uri),indent=2))
    return 0


if __name__=="__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # The shell invokes pythonw without a visible console. Persist click
        # failures locally for investigation without editing production data.
        try:
            error_dir=queue_folder().parent
            error_dir.mkdir(parents=True,exist_ok=True)
            with (error_dir/"navigation-errors.log").open("a",encoding="utf-8") as log:
                log.write(datetime.now(timezone.utc).isoformat()+
                          f" {type(exc).__name__}: {exc}\n")
        except Exception:
            pass
        print(f"REPORTAPP LINK ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
