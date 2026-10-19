"""Fail-closed, read-only source verification before clickable desktop alerts.

Never search by surveyor/creator, never navigate here, never write GIS data.
A popup remains useful when service lookup is unavailable, but must not
advertise an unverified navigation action.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from collections.abc import Mapping
from .exact_feature_lookup import ExactFeatureMismatch, resolve_exact_feature
from .alert_navigation import ASSET_LAYER_IDS, zoom_uri


def verified_source_uri(alert, config, *, layer=None, layer_factory=None):
    """Re-fetch this exact immutable event identity on sde.DEFAULT.

    No fallback to latest by creator, no substituted OBJECTID. The original
    captured source event time and editor remain authoritative; a newer
    edit invalidates the old click target.
    """
    asset = str(alert["asset"]).strip().casefold()
    if asset not in ASSET_LAYER_IDS:
        raise ValueError("Unsupported REG navigation asset")
    version = str(config.get("version") or "sde.DEFAULT")
    if version.casefold() != "sde.default":
        raise ValueError("The source version must be sde.DEFAULT.")
    globalid = alert["globalid"]
    oid = alert["objectid"]
    event = alert["event_time_utc_ms"]
    actor = alert["username"]
    if layer is None:
        if layer_factory is None:
            from arcgis.features import FeatureLayer
            from .progress_report import DEFAULT_LINE_SERVICE_URL
            from .surveyor_notifications import _monitor_gis
            root = str(config.get("feature_service_url") or
                       DEFAULT_LINE_SERVICE_URL).rstrip("/")
            layer = FeatureLayer(
                f"{root}/{ASSET_LAYER_IDS[asset]}", _monitor_gis(config))
        else:
            layer = layer_factory(asset, config)
    resolve_exact_feature(
        layer, globalid=globalid, objectid=oid, gdb_version=version,
        event_time_utc_ms=event, actor=actor,
    )
    return zoom_uri(
        asset, oid, globalid=globalid,
        event_time_utc_ms=event, actor=actor, gdb_version=version,
    )


def safe_verified_source_uri(alert, config, *, layer=None, layer_factory=None):
    """Return only a proven current source link; no network failures leaked.

    Exceptions never trigger OBJECTID-only fallback; notify normally with
    no clickable zoom and let the user inspect the Inbox record.
    """
    try:
        return verified_source_uri(
            alert, config, layer=layer, layer_factory=layer_factory)
    except Exception as exc:
        # ArcGIS Enterprise can raise provider-specific exceptions including
        # ImportError, request errors and expired-token errors. Never allow a
        # source verification problem to prevent delivery of the QA popup.
        # Log only the exception type to avoid credentials or source leakage.
        import logging
        logging.getLogger(__name__).warning(
            "REPORTAPP exact source validation prevented navigation: %s",
            type(exc).__name__,
        )
        return ""


def verified_scanned_event_uri(alert, config, *, now_ms=None):
    """Deep-link the exact event from a successful authenticated batch scan.

    The watcher has *already* queried the source on explicit sde.DEFAULT.
    Re-querying for every popup can fail on a different overloaded ArcGIS
    instance and silently strip all zoom buttons. Treat the collected source
    attributes as scan-time evidence, NOT a guarantee of current map state.
    The ArcGIS Pro Bridge MUST recheck the live source before selecting.
    """
    attrs=alert.get("source_scan_evidence")
    captured=alert.get("source_scan_at_utc_ms")
    if not isinstance(attrs,Mapping) or isinstance(captured,bool):
        raise ValueError("No valid completed REG source scan evidence.")
    now=int(now_ms if now_ms is not None
            else datetime.now(timezone.utc).timestamp()*1000)
    try:
        age=now-int(captured)
    except (TypeError,ValueError) as exc:
        raise ValueError("No scan completion timestamp.") from exc
    if not 0<=age<=10*60*1000:
        raise ValueError("Scan evidence expired; new source check required.")
    if alert.get("deferred_historical"):
        raise ValueError("Historical alerts require current source recheck.")
    # Reuse exact_feature_lookup's full identity verifier; it requires the
    # queried fields and rechecks timestamp, actor, GUID and OBJECTID. No
    # unverified OBJECTID-only navigation is constructed.
    class ScannedFeature:
        def query(self,**kwargs):
            if (kwargs.get("gdb_version")!="sde.DEFAULT"
                    or kwargs.get("return_geometry") is not False):
                raise ExactFeatureMismatch("Snapshot requires sde.DEFAULT attributes.")
            return SimpleNamespace(features=[
                SimpleNamespace(attributes=dict(attrs))
            ])
    return verified_source_uri(alert,config,layer=ScannedFeature())


def safe_scanned_event_uri(alert, config, *, now_ms=None):
    """Preserve popup delivery without claiming navigation on unsafe evidence."""
    try:
        return verified_scanned_event_uri(alert,config,now_ms=now_ms)
    except (Exception) as exc:
        import logging
        logging.getLogger(__name__).warning(
            "REPORTAPP scan evidence prevented deep-link: %s",
            type(exc).__name__,
        )
        return ""
