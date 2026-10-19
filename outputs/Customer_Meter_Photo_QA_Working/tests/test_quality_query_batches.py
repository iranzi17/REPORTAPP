from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meter_photo_qa.quality_query_batches import query_attributes_in_batches
from meter_photo_qa.quality_watcher import _query_quality_attributes, load_quality_rules


class FakeLineService:
    def __init__(self, records, area_ids=None, max_records=2000):
        self.records = {int(v["OBJECTID"]): v for v in records}
        self.area_ids = area_ids or {"whole": list(self.records)}
        self.properties = SimpleNamespace(maxRecordCount=max_records)
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if kwargs.get("return_count_only"):
            result = self.area_ids.get(kwargs.get("geometry_filter"), [])
            return len(result) if result is not None else 0
        if kwargs.get("return_ids_only"):
            return {"objectIds": self.area_ids.get(kwargs.get("geometry_filter"), [])}
        if "object_ids" in kwargs:
            requested = [int(value) for value in kwargs["object_ids"].split(",")]
            return SimpleNamespace(features=[
                SimpleNamespace(attributes=self.records[oid])
                for oid in requested if oid in self.records
            ])
        raise AssertionError("Unsafe spatial full-record query was attempted.")


def make_rows(count):
    return [{"OBJECTID": i, "GLOBALID": f"{{G-{i}}}", "ASSETGROUP": 9}
            for i in range(1, count + 1)]


def query_batch(fake, filters, size=150, progress=None):
    return query_attributes_in_batches(
        layer=fake,
        where="ASSETGROUP IN (9,10)", version="sde.DEFAULT",
        fields=["OBJECTID", "GLOBALID", "ASSETGROUP"],
        geometry_filters=filters, query_fn=lambda layer, **kwargs: layer.query(**{
            k: v for k, v in kwargs.items() if k != "attempts"
        }),
        batch_size=size, progress=progress,
    )


class QualityBatchTests(unittest.TestCase):
    def test_duplicated_crossing_lines_counted_once(self):
        layer = FakeLineService(make_rows(4), area_ids={"sectorA": [1, 2, 3], "sectorB": [3, 4]})
        rows = query_batch(layer, [("Burera / X", "sectorA"), ("Rulindo / Y", "sectorB")])
        self.assertEqual([row["OBJECTID"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(sum(bool(q.get("return_ids_only")) for q in layer.queries), 2)
        attrs = [q for q in layer.queries if "object_ids" in q]
        self.assertEqual(len(attrs), 1)
        self.assertNotIn("geometry_filter", attrs[0])

    def test_batches_use_objectids_and_honor_max_record_count(self):
        layer = FakeLineService(make_rows(205), area_ids={"A": list(range(1, 206))}, max_records=75)
        rows = query_batch(layer, [("A", "A")], size=150)
        self.assertEqual(len(rows), 205)
        attrs = [q for q in layer.queries if "object_ids" in q]
        self.assertEqual([len(q["object_ids"].split(",")) for q in attrs], [75, 75, 55])
        self.assertTrue(all(q.get("return_all_records") is False for q in attrs))

    def test_manual_safety_cap_stops_before_attribute_queries(self):
        service=FakeLineService(make_rows(15),area_ids={"all":list(range(1,16))})
        with self.assertRaisesRegex(RuntimeError,"manual scan safety cap"):
            query_attributes_in_batches(
                service,"1=1","sde.DEFAULT",["OBJECTID","GLOBALID"],
                [("Recent surveyor data","all")],
                lambda layer,**kw:layer.query(**{k:v for k,v in kw.items() if k!="attempts"}),
                max_matching_ids=10,query_attempts=1,
            )
        self.assertEqual(len(service.queries),1)
        self.assertTrue(service.queries[0]["return_ids_only"])
        self.assertFalse(any("object_ids" in q for q in service.queries))

    def test_manual_cap_allows_small_eligible_snapshot(self):
        service=FakeLineService(make_rows(3),area_ids={"all":[1,2,3]})
        rows=query_attributes_in_batches(
            service,"1=1","sde.DEFAULT",["OBJECTID","GLOBALID"],
            [("Recent surveyor data","all")],
            lambda layer,**kw:layer.query(**{k:v for k,v in kw.items() if k!="attempts"}),
            max_matching_ids=3,query_attempts=1,
        )
        self.assertEqual(len(rows),3)
        self.assertEqual(sum("object_ids" in q for q in service.queries),1)

    def test_no_matching_rows_returns_empty_without_attribute_request(self):
        layer = FakeLineService(make_rows(1), area_ids={"A": []})
        self.assertEqual(query_batch(layer, [("A", "A")]), [])
        self.assertEqual(len(layer.queries), 1)

    def test_arcgis_null_objectids_with_verified_zero_count_is_empty(self):
        # ArcGIS Feature Service often emits {'objectIds': None} for
        # polygons containing no distribution transformers.
        layer = FakeLineService(make_rows(2), area_ids={"Muzo": None, "Gakenke": [1, 2]})
        messages = []
        rows = query_batch(
            layer, [("Gakenke / Muzo", "Muzo"),
                    ("Gakenke / Gakenke", "Gakenke")],
            progress=messages.append,
        )
        self.assertEqual([row["OBJECTID"] for row in rows], [1, 2])
        count_calls = [q for q in layer.queries if q.get("return_count_only")]
        self.assertEqual(len(count_calls), 1)
        self.assertEqual(count_calls[0]["geometry_filter"], "Muzo")
        self.assertEqual(count_calls[0]["gdb_version"], "sde.DEFAULT")
        self.assertIn("ASSETGROUP", count_calls[0]["where"])
        self.assertTrue(any("no matching features in Gakenke / Muzo" in m for m in messages))

    def test_missing_objectids_key_with_zero_count_is_also_empty(self):
        layer = FakeLineService(make_rows(1), area_ids={"Muzo": []})
        def query(target, **kwargs):
            clean = {key: val for key, val in kwargs.items() if key != "attempts"}
            if clean.get("return_ids_only"):
                return {"objectIdFieldName": "OBJECTID"}
            return target.query(**clean)
        self.assertEqual(query_attributes_in_batches(
            layer, "ASSETGROUP = 12", "sde.DEFAULT",
            ["OBJECTID"], [("Gakenke / Muzo", "Muzo")], query,
        ), [])
        self.assertEqual(len([q for q in layer.queries if q.get("return_count_only")]), 1)

    def test_missing_objectids_with_positive_count_aborts(self):
        layer = FakeLineService(make_rows(2), area_ids={"Muzo": [1, 2]})
        def query(target, **kwargs):
            clean = {key: val for key, val in kwargs.items() if key != "attempts"}
            if clean.get("return_ids_only"):
                return {"objectIds": None}
            return target.query(**clean)
        with self.assertRaisesRegex(RuntimeError, "matching count is 2"):
            query_attributes_in_batches(
                layer, "1=1", "sde.DEFAULT", ["OBJECTID"],
                [("Gakenke / Muzo", "Muzo")], query,
            )

    def test_missing_objectids_and_broken_count_query_aborts(self):
        layer = FakeLineService(make_rows(1), area_ids={"Muzo": []})
        def query(target, **kwargs):
            if kwargs.get("return_ids_only"):
                return {"objectIds": None}
            if kwargs.get("return_count_only"):
                raise RuntimeError("Count endpoint unavailable")
            return target.query(**{key: val for key, val in kwargs.items()
                                  if key != "attempts"})
        with self.assertRaisesRegex(RuntimeError, "count-only verification failed"):
            query_attributes_in_batches(
                layer, "1=1", "sde.DEFAULT", ["OBJECTID"],
                [("Gakenke / Muzo", "Muzo")], query,
            )

    def test_invalid_id_response_cannot_be_silent_zero(self):
        layer = FakeLineService(make_rows(1))
        with self.assertRaisesRegex(RuntimeError, "invalid objectIds"):
            query_attributes_in_batches(
                layer, "1=1", "sde.DEFAULT", ["OBJECTID"], [("Muzo", "Muzo")],
                lambda _layer, **kwargs: {"objectIds": "not-an-array"},
            )

    def test_53_polygon_transformer_run_continues_after_empty_muzo(self):
        # This models the reported 1/53 failure, without a live server.
        layer = FakeLineService(
            make_rows(2), area_ids={
                **{"sector-" + str(i): None for i in range(1, 54)},
                "sector-12": [1],
                "sector-53": [1, 2],
            },
        )
        areas = [
            (f"Gakenke / Sector {i}", f"sector-{i}") for i in range(1, 54)
        ]
        rows = query_batch(layer, areas)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            len([q for q in layer.queries if q.get("return_count_only")]), 51,
        )
        self.assertEqual(
            len([q for q in layer.queries if q.get("return_ids_only")]), 53,
        )


    @patch("meter_photo_qa.quality_query_batches.time.sleep")
    def test_transient_sde_default_version_error_retries_same_polygon_once(self, sleep):
        layer = FakeLineService(make_rows(2), area_ids={"A": [1, 2]})
        calls = []
        def flaky(target, **kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise RuntimeError(
                    "ArcGIS query failed after 2 attempts: "
                    "Failed to find Version 'sde.DEFAULT'. (Error Code: 400)"
                )
            return target.query(**{
                k: v for k, v in kwargs.items() if k != "attempts"
            })
        messages=[]
        result=query_attributes_in_batches(
            layer, "ASSETGROUP IN (9,10)", "sde.DEFAULT",
            ["OBJECTID","GLOBALID"], [("Gakenke / Ruli", "A")],
            flaky, progress=messages.append,
        )
        self.assertEqual(len(result),2)
        sleep.assert_called_once_with(8)
        self.assertEqual(calls[0]["attempts"],2)
        self.assertEqual(calls[1]["attempts"],1)
        self.assertEqual(calls[0]["gdb_version"],"sde.DEFAULT")
        self.assertEqual(calls[0]["geometry_filter"],calls[1]["geometry_filter"])
        self.assertEqual(calls[0]["where"],calls[1]["where"])
        self.assertEqual(calls[1]["gdb_version"],"sde.DEFAULT")
        self.assertTrue(any("source version unchanged" in x for x in messages))

    @patch("meter_photo_qa.quality_query_batches.time.sleep")
    def test_persistent_missing_default_version_cancels_without_attribute_query(self, sleep):
        layer=FakeLineService(make_rows(1),area_ids={"A":[1]})
        calls=[]
        def missing(target,**kwargs):
            calls.append(kwargs)
            if kwargs.get("geometry_filter")=="A":
                raise RuntimeError("Failed to find Version 'sde.DEFAULT'. (Error Code: 400)")
            return target.query(**{
                k: v for k,v in kwargs.items() if k!="attempts"
            })
        with self.assertRaisesRegex(RuntimeError,"NOT generated.*Failed to find Version"):
            query_attributes_in_batches(
                layer,"1=1","sde.DEFAULT",["OBJECTID","GLOBALID"],
                [("Gakenke / Ruli","A")],missing,
            )
        self.assertEqual(len(calls),2)
        self.assertEqual([x["attempts"] for x in calls],[2,1])
        self.assertTrue(all(x["gdb_version"]=="sde.DEFAULT" for x in calls))
        self.assertFalse(any("object_ids" in x for x in calls))
        sleep.assert_called_once_with(8)

    @patch("meter_photo_qa.quality_query_batches.time.sleep")
    def test_failed_other_version_never_falls_back_or_retries(self,sleep):
        calls=[]
        def missing(target,**kwargs):
            calls.append(kwargs)
            raise RuntimeError("Failed to find Version 'another.VERSION'. (Error Code: 400)")
        with self.assertRaisesRegex(RuntimeError,"NOT generated"):
            query_attributes_in_batches(
                SimpleNamespace(properties=SimpleNamespace(maxRecordCount=2000)),
                "1=1","another.VERSION",["OBJECTID"],
                [("A",None)],missing,
            )
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["gdb_version"],"another.VERSION")
        sleep.assert_not_called()

    @patch("meter_photo_qa.quality_query_batches.time.sleep")
    def test_count_verification_rechecks_version_before_confirming_empty(self,sleep):
        layer=FakeLineService(make_rows(1),area_ids={"A":None})
        count_attempts=[]
        def maybe(target,**kwargs):
            if kwargs.get("return_count_only"):
                count_attempts.append(kwargs["attempts"])
                if len(count_attempts)==1:
                    raise RuntimeError("Failed to find Version 'sde.DEFAULT' (Error Code: 400)")
            return target.query(**{k:v for k,v in kwargs.items() if k!="attempts"})
        rows=query_attributes_in_batches(
            layer,"1=1","sde.DEFAULT",["OBJECTID"],
            [("Gakenke / Muzo","A")],maybe,
        )
        self.assertEqual(rows,[])
        self.assertEqual(count_attempts,[2,1])
        sleep.assert_called_once_with(8)

    @patch("meter_photo_qa.quality_query_batches.time.sleep")
    def test_attribute_batch_version_recheck_preserves_requested_oids(self,sleep):
        layer=FakeLineService(make_rows(2),area_ids={"A":[1,2]})
        batch_queries=[]
        def flaky(target,**kwargs):
            if "object_ids" in kwargs:
                batch_queries.append(dict(kwargs))
                if len(batch_queries)==1:
                    raise RuntimeError("Failed to find Version 'sde.DEFAULT' (Error Code: 400)")
            return target.query(**{k:v for k,v in kwargs.items() if k!="attempts"})
        rows=query_attributes_in_batches(
            layer,"1=1","sde.DEFAULT",["OBJECTID","GLOBALID"],
            [("A","A")],flaky,
        )
        self.assertEqual(len(rows),2)
        self.assertEqual(batch_queries[0]["object_ids"],batch_queries[1]["object_ids"])
        self.assertEqual(batch_queries[1]["gdb_version"],"sde.DEFAULT")
        sleep.assert_called_once_with(8)

    def test_503_fails_without_partial_report(self):
        layer = FakeLineService(make_rows(3))
        def simulated(layer, **kwargs):
            if kwargs.get("geometry_filter") == "B":
                raise RuntimeError("503 timeout")
            return layer.query(**{k: v for k, v in kwargs.items() if k != "attempts"})
        with self.assertRaisesRegex(RuntimeError, "B.*NOT generated.*503"):
            query_attributes_in_batches(
                layer, "1=1", "sde.DEFAULT", ["OBJECTID"],
                [("A", "whole"), ("B", "B")], simulated
            )
        self.assertEqual(sum("object_ids" in q for q in layer.queries), 0)

    def test_missing_attribute_row_cancels_full_report(self):
        layer = FakeLineService(make_rows(3), area_ids={"A": [1, 2, 3]})
        del layer.records[2]
        with self.assertRaisesRegex(RuntimeError, "omitted 1 requested"):
            query_batch(layer, [("A", "A")])

    def test_duplicate_globalids_in_distinct_oids_are_rejected(self):
        rows = make_rows(2)
        rows[1]["GLOBALID"] = rows[0]["GLOBALID"]
        layer = FakeLineService(rows, area_ids={"A": [1, 2]})
        with self.assertRaisesRegex(RuntimeError, "Duplicate GlobalID"):
            query_batch(layer, [("A", "A")])

    def test_opt_in_duplicate_globalid_reporting_keeps_both_oids(self):
        rows = make_rows(3)
        rows[2]["GLOBALID"] = rows[0]["GLOBALID"].lower().strip("{}")
        layer = FakeLineService(rows, area_ids={"A": [1, 2, 3]})
        progress = []
        result = query_attributes_in_batches(
            layer, "ASSETGROUP IN (9,10)", "sde.DEFAULT",
            ["OBJECTID", "GLOBALID"], [("A", "A")],
            lambda lyr, **kw: lyr.query(**{k:v for k,v in kw.items() if k!="attempts"}),
            batch_size=2, progress=progress.append,
            duplicate_globalid_policy="report",
        )
        self.assertEqual([rec["OBJECTID"] for rec in result], [1, 2, 3])
        self.assertTrue(any("DATA INTEGRITY WARNING" in message for message in progress))

    def test_duplicate_policy_is_explicit(self):
        layer = FakeLineService(make_rows(1))
        with self.assertRaisesRegex(ValueError, "duplicate_globalid_policy"):
            query_attributes_in_batches(
                layer, "1=1", "sde.DEFAULT", ["OBJECTID"],
                [("A", "A")], lambda lyr, **kw: lyr.query(**kw),
                duplicate_globalid_policy="ignore",
            )

    def test_unexpected_response_format_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "ObjectID dictionary"):
            query_attributes_in_batches(
                SimpleNamespace(properties={}),
                "1=1", "sde.DEFAULT", ["OBJECTID"], [("A", "A")],
                lambda *_args, **_kwargs: SimpleNamespace(features=[]),
            )

    def test_single_area_with_no_geometry_can_still_query_all_rwanda(self):
        layer = FakeLineService(make_rows(2), area_ids={None: [1, 2]})
        rows = query_batch(layer, [("All Rwanda", None)])
        self.assertEqual(len(rows), 2)
        self.assertNotIn("geometry_filter", layer.queries[0])

    def test_empty_boundaries_fail_instead_of_executing_national_query(self):
        layer = FakeLineService(make_rows(3))
        with self.assertRaisesRegex(ValueError, "No boundary polygons"):
            query_batch(layer, [])

    def test_progress_reports_after_batch_completion(self):
        messages = []
        layer = FakeLineService(make_rows(3), area_ids={"A": [1, 2, 3]})
        query_batch(layer, [("A", "A")], progress=messages.append)
        self.assertTrue(any("identified" in msg for msg in messages))
        self.assertTrue(any("Loaded 3/3" in msg for msg in messages))

    def test_watcher_passes_individual_sector_geometries_not_giant_union(self):
        class FakeGeometry:
            def __init__(self, geom):
                self.geom = geom
        faux_arcgis = types.ModuleType("arcgis")
        faux_geometry = types.ModuleType("arcgis.geometry")
        faux_filters = types.ModuleType("arcgis.geometry.filters")
        faux_filters.intersects = lambda geometry, sr=None: geometry["sector"]
        boundary = SimpleNamespace(
            spatial_reference={"wkid": 4326},
            features=[
                SimpleNamespace(geometry={"rings": [[[0,0], [1,0], [0,1]]], "sector": "A"},
                                attributes={"district": "Burera", "sector": "X"}),
                SimpleNamespace(geometry={"rings": [[[0,0], [2,0], [0,2]]], "sector": "B"},
                                attributes={"district": "Gakenke", "sector": "Y"}),
            ],
        )
        layer = FakeLineService(make_rows(3), area_ids={"A": [1,2], "B": [2,3]})
        rules = load_quality_rules()
        with patch.dict(sys.modules, {
            "arcgis": faux_arcgis,
            "arcgis.geometry": faux_geometry,
            "arcgis.geometry.filters": faux_filters,
        }), patch("meter_photo_qa.quality_watcher._query_with_retry",
                 side_effect=lambda target, **kw: target.query(**{
                     k:v for k,v in kw.items() if k != "attempts"
                 })):
            rows = _query_quality_attributes(
                layer, "1=1", "sde.DEFAULT", None, rules,
                sector_feature_set=boundary,
            )
        self.assertEqual(len(rows), 3)
        self.assertEqual([q["geometry_filter"] for q in layer.queries if q.get("return_ids_only")], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
