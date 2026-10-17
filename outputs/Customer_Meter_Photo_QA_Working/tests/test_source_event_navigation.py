"""Exact source recheck and Source Event Time / creator collision regressions."""
from __future__ import annotations
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import sys
import types
import unittest

from meter_photo_qa import source_event_navigation as navigation
from meter_photo_qa.exact_feature_lookup import ExactFeatureMismatch

GID = "{142A4DBA-F393-4597-90A9-3878A86827B9}"
OTHER = "{142A4DBA-F393-4597-90A9-3878A86827B8}"
TIME_MS = 1792161960000
CONFIG = {"version": "sde.DEFAULT", "feature_service_url":
          "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"}
ALERT = {"asset": "pole", "objectid": 891705, "globalid": GID,
         "event_time_utc_ms": TIME_MS, "username": "ninamenye9683",
         "event_type": "EDIT"}


class Layer:
    def __init__(self, features):
        self.features = features
        self.calls = []

    def query(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(features=self.features)


def feature(*, oid=891705, gid=GID, edited=TIME_MS, editor="ninamenye9683",
            created=TIME_MS - 100000, creator="ninamenye9683"):
    return SimpleNamespace(attributes={
        "OBJECTID": oid, "GLOBALID": gid,
        "created_date": created, "created_user": creator,
        "last_edited_date": edited, "last_edited_user": editor})


class ExactLiveEventTests(unittest.TestCase):
    def test_same_surveyor_new_pole_cannot_replace_edited_old_pole(self):
        layer = Layer([feature(oid=891706, gid=OTHER)])
        self.assertEqual(navigation.safe_verified_source_uri(
            ALERT, CONFIG, layer=layer), "")
        self.assertEqual(layer.calls[0]["where"],
                         "GlobalID='{142a4dba-f393-4597-90a9-3878a86827b9}'")
        self.assertFalse(layer.calls[0]["return_geometry"])
        self.assertEqual(layer.calls[0]["gdb_version"], "sde.DEFAULT")

    def test_correct_old_edited_pole_has_exact_source_event_link(self):
        layer = Layer([feature()])
        uri = navigation.verified_source_uri(ALERT, CONFIG, layer=layer)
        self.assertIn("/pole/891705?", uri)
        self.assertIn("event_ms=1792161960000", uri)
        self.assertIn("actor=ninamenye9683", uri)
        self.assertIn("ver=sde.DEFAULT", uri)
        self.assertIn("gid=142a4dba-f393-4597-90a9-3878a86827b9", uri)

    def test_source_event_time_now_changed_never_generates_stale_link(self):
        layer = Layer([feature(edited=TIME_MS + 60000)])
        self.assertEqual(navigation.safe_verified_source_uri(
            ALERT, CONFIG, layer=layer), "")

    def test_same_pole_wrong_editor_rejected(self):
        layer = Layer([feature(editor="other_surveyor")])
        self.assertEqual(navigation.safe_verified_source_uri(ALERT, CONFIG, layer=layer), "")

    def test_same_creator_wrong_globalid_rejected(self):
        layer = Layer([feature(gid=OTHER)])
        self.assertEqual(navigation.safe_verified_source_uri(ALERT, CONFIG, layer=layer), "")

    def test_not_found_or_ambiguous_source_fails_closed(self):
        for result in ([], [feature(), feature()]):
            with self.subTest(total=len(result)):
                layer = Layer(result)
                self.assertEqual(navigation.safe_verified_source_uri(
                    ALERT, CONFIG, layer=layer), "")
                self.assertEqual(len(layer.calls), 1)

    def test_mismatched_version_is_rejected_without_network(self):
        wrong = dict(CONFIG, version="surveyors.working")
        layer = Layer([feature()])
        self.assertEqual(navigation.safe_verified_source_uri(ALERT, wrong, layer=layer), "")
        self.assertEqual(layer.calls, [])

    def test_connection_error_does_not_fallback_to_objectid_uri(self):
        class OfflineLayer:
            def query(self, **kwargs):
                raise OSError("service temporarily unavailable")
        self.assertEqual(navigation.safe_verified_source_uri(
            ALERT, CONFIG, layer=OfflineLayer()), "")

    def test_arcgis_provider_error_keeps_alert_but_never_creates_link(self):
        class ArcGISProviderFailure(Exception):
            pass
        class Remote:
            def query(self, **kwargs):
                raise ArcGISProviderFailure("opaque provider error")
        self.assertEqual(navigation.safe_verified_source_uri(
            ALERT, CONFIG, layer=Remote()), "")

    def test_clean_activity_same_actor_can_carry_verified_context(self):
        entry = dict(ALERT, notification_kind="CLEAN_ACTIVITY", issues=[])
        uri = navigation.verified_source_uri(entry, CONFIG, layer=Layer([feature()]))
        self.assertIn("gid=", uri)
        self.assertIn("event_ms=", uri)

    def test_clean_toast_action_has_exact_identity_and_source_time(self):
        from unittest.mock import Mock
        from meter_photo_qa.surveyor_activity import deliver_clean_activity
        toast=Mock()
        supplier=Mock(return_value=toast)
        import sys
        from meter_photo_qa.alert_navigation import zoom_uri
        expected=zoom_uri(
            "pole", 891705, globalid=GID, event_time_utc_ms=TIME_MS,
            actor="ninamenye9683", gdb_version="sde.DEFAULT",
        )
        with patch.dict(sys.modules, {
            "winotify": SimpleNamespace(Notification=supplier),
        }), patch(
            "meter_photo_qa.alert_navigation.is_registered",return_value=True
        ), patch(
            "meter_photo_qa.source_event_navigation.verified_source_uri",
            return_value=expected
        ):
            deliver_clean_activity(
                dict(ALERT,issues=[],notification_kind="CLEAN_ACTIVITY"), CONFIG)
        self.assertEqual(supplier.call_args.kwargs["launch"],expected)
        toast.add_actions.assert_called_once_with(
            label="Zoom in ArcGIS Pro",launch=expected)
        toast.show.assert_called_once()

    def test_clean_toast_does_not_offer_unsafe_zoom_if_source_changed(self):
        from unittest.mock import Mock
        from meter_photo_qa.surveyor_activity import deliver_clean_activity
        import sys
        toast=Mock()
        supplier=Mock(return_value=toast)
        with patch.dict(sys.modules, {
            "winotify": SimpleNamespace(Notification=supplier),
        }), patch(
            "meter_photo_qa.alert_navigation.is_registered",return_value=True
        ), patch(
            "meter_photo_qa.source_event_navigation.verified_source_uri",
            side_effect=ExactFeatureMismatch("stale source")
        ):
            deliver_clean_activity(
                dict(ALERT,issues=[],notification_kind="CLEAN_ACTIVITY"), CONFIG)
        self.assertEqual(supplier.call_args.kwargs["launch"],"")
        toast.add_actions.assert_not_called()
        toast.show.assert_called_once()

    def test_old_created_pole_with_later_edit_by_same_actor_matches_edit_event(self):
        layer = Layer([feature(created=TIME_MS - 36000000, edited=TIME_MS)])
        self.assertEqual(navigation.verified_source_uri(
            ALERT, CONFIG, layer=layer).count("actor="), 1)

    def test_no_unverified_uri_on_malformed_guid(self):
        bad = dict(ALERT, globalid="some latest item")
        layer = Layer([feature()])
        self.assertEqual(navigation.safe_verified_source_uri(
            bad, CONFIG, layer=layer), "")
        self.assertEqual(layer.calls, [])

    def test_verified_link_factory_uses_only_exact_authorized_layer(self):
        urls = []
        def source_layer(asset, config):
            urls.append(asset)
            return Layer([feature()])
        uri = navigation.verified_source_uri(
            ALERT, CONFIG, layer_factory=source_layer)
        self.assertEqual(urls, ["pole"])
        self.assertIn("event_ms=", uri)


if __name__ == "__main__":
    unittest.main()
