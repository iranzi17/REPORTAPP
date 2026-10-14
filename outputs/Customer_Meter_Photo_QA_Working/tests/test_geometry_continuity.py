from __future__ import annotations
import unittest
from meter_photo_qa.geometry_continuity import group_line_continuity

def line(oid, user, a, b, name="Central", group=9):
    return {
        "attributes":{
            "OBJECTID":oid,"GLOBALID":"{L-%s}"%oid,
            "ASSETGROUP":group,"created_user":user,"Transformer_Name":name,
        },
        "geometry":{"paths":[[list(a),list(b)]],
                    "spatialReference":{"wkid":3857}},
    }

def transformer(oid, x, y, name="Central"):
    return {
        "attributes":{"OBJECTID":oid,"GLOBALID":"{T-%s}"%oid,
                      "ASSETGROUP":12,"Transfomer_name_":name},
        "geometry":{"x":x,"y":y,"spatialReference":{"wkid":3857}},
    }

class EndpointGeometryTests(unittest.TestCase):
    def test_same_creator_chain_continues_beyond_source_district_without_trace(self):
        data=[
            line(1,"edison",(0,0),(10,0)),
            line(2,"edison",(10,0),(20,0)),
            line(3,"edison",(20,0),(30,0)),
            line(4,"other",(30,0),(40,0)),
            line(5,"edison",(200,0),(210,0)),
        ]
        r=group_line_continuity(data,[transformer(100,0.2,0)])
        by_oid={v["objectid"]:v for v in r["results"]}
        for oid in (1,2,3):
            self.assertEqual(by_oid[oid]["status"],"PROVISIONAL_GEOMETRY_MATCH")
            self.assertEqual(by_oid[oid]["component_size"],3)
            self.assertEqual(by_oid[oid]["source_objectids"],[100])
        self.assertEqual(by_oid[4]["status"],"NO_DISTRICT_START_GEOMETRY")
        self.assertEqual(by_oid[5]["status"],"NO_DISTRICT_START_GEOMETRY")

    def test_creator_mismatch_does_not_auto_bridge_connected_endpoints(self):
        r=group_line_continuity([
            line(1,"edison",(0,0),(10,0)),
            line(2,"ringuyeneza",(10,0),(20,0)),
            line(3,"edison",(20,0),(30,0)),
        ],[transformer(100,0,0)])
        by_oid={x["objectid"]:x for x in r["results"]}
        self.assertEqual(by_oid[1]["source_count"],1)
        self.assertEqual(by_oid[2]["source_count"],0)
        self.assertEqual(by_oid[3]["source_count"],0)

    def test_small_gap_is_suggestion_never_auto_connected(self):
        r=group_line_continuity([
            line(1,"edison",(0,0),(10,0)),
            line(2,"edison",(12.4,0),(22.4,0)),
        ],[transformer(100,0,0)])
        by_oid={x["objectid"]:x for x in r["results"]}
        self.assertEqual(by_oid[1]["source_count"],1)
        self.assertEqual(by_oid[2]["source_count"],0)
        self.assertEqual(r["suggested_gaps"][0]["line_oid_b"],2)
        self.assertGreater(r["suggested_gaps"][0]["distance_m"],1.5)

    def test_multiple_transformer_sources_are_ambiguous(self):
        r=group_line_continuity([
            line(1,"edison",(0,0),(10,0)),
            line(2,"edison",(10,0),(20,0)),
        ],[transformer(100,0,0),transformer(101,20,0)])
        self.assertTrue(all(x["status"]=="MULTIPLE_TRANSFORMERS_NEAR_COMPONENT"
                            for x in r["results"]))
        self.assertTrue(all(x["transformer_objectid"] is None for x in r["results"]))

    def test_same_geometry_wrong_transformer_name_is_review_only(self):
        r=group_line_continuity([
            line(1,"edison",(0,0),(10,0),name="Wrong")
        ],[transformer(100,0,0,name="Central")])
        self.assertEqual(r["results"][0]["status"],"NAME_DIFFERENCE_PROVISIONAL")
        self.assertIn("NOT verified",r["results"][0]["evidence"])

    def test_non_lv_line_and_missing_geometry_fail(self):
        with self.assertRaisesRegex(RuntimeError,"Non-LV"):
            group_line_continuity(
                [line(5,"edison",(0,0),(1,0),group=2)],[])
        with self.assertRaisesRegex(RuntimeError,"Missing LV line geometry"):
            group_line_continuity([
                {"attributes":{"OBJECTID":6,"ASSETGROUP":9},
                 "geometry":{"paths":[]}}
            ],[])

    def test_invalid_tolerances_are_rejected(self):
        with self.assertRaises(ValueError):
            group_line_continuity([],[],endpoint_tolerance=50)
        with self.assertRaises(ValueError):
            group_line_continuity([],[],seed_tolerance=0.1)

if __name__=="__main__":
    unittest.main()
