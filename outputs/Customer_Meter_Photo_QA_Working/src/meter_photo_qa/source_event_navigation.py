"""Fail-closed, read-only source verification before clickable desktop alerts.

Never search by surveyor/creator, never navigate here, never write GIS data.
A popup remains useful when service lookup is unavailable, but must not
advertise an unverified navigation action.
"""
from __future__ import annotations

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
    except (ExactFeatureMismatch, ValueError, KeyError, TypeError, RuntimeError,
            OSError):
        return ""
