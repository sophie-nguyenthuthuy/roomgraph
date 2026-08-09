"""End to end against the fixtures' declared ground truth."""

from __future__ import annotations

import unittest

from support import ground_truth, plan

from roomgraph.geom import Pt
from roomgraph.model import extract
from roomgraph.planar import build_arrangement
from roomgraph.rooms import classify
from roomgraph.scale import PT_TO_MM, determine_scale, parse_scale_arg
from roomgraph.walls import (
    Wall,
    complement,
    extract_walls,
    intersect_intervals,
    merge_intervals,
)


class TestIntervalAlgebra(unittest.TestCase):
    def test_merge_touching(self):
        self.assertEqual(merge_intervals([(0, 5), (5, 10)]), [(0, 10)])

    def test_merge_respects_gap_tolerance(self):
        self.assertEqual(merge_intervals([(0, 5), (7, 10)], gap=3), [(0, 10)])
        self.assertEqual(merge_intervals([(0, 5), (7, 10)], gap=1), [(0, 5), (7, 10)])

    def test_merge_normalises_reversed(self):
        self.assertEqual(merge_intervals([(10, 0)]), [(0, 10)])

    def test_intersect(self):
        self.assertEqual(intersect_intervals([(0, 10)], [(5, 15)]), [(5, 10)])
        self.assertEqual(intersect_intervals([(0, 10)], [(20, 30)]), [])

    def test_complement_finds_the_gap(self):
        self.assertEqual(complement([(0, 4), (6, 10)], 0, 10), [(4, 6)])

    def test_complement_of_nothing_is_everything(self):
        self.assertEqual(complement([], 0, 10), [(0, 10)])


class TestScaleParsing(unittest.TestCase):
    def test_ratio(self):
        self.assertAlmostEqual(parse_scale_arg("1:50"), 50 * PT_TO_MM)

    def test_bare_denominator(self):
        self.assertAlmostEqual(parse_scale_arg("100"), 100 * PT_TO_MM)

    def test_explicit_mm(self):
        self.assertAlmostEqual(parse_scale_arg("17.64mm"), 17.64)

    def test_rejects_nonsense(self):
        self.assertIsNone(parse_scale_arg("banana"))
        self.assertIsNone(parse_scale_arg("1"))


class TestWallExtraction(unittest.TestCase):
    def test_apartment_walls(self):
        from roomgraph.pdf.content import read_pdf

        geo = read_pdf(plan("apartment.pdf"))
        scale = determine_scale(geo)
        walls = extract_walls(geo, scale.mm_per_pt)
        self.assertEqual(len(walls), 6)

        thicknesses = sorted(round(w.thickness) for w in walls)
        self.assertEqual(thicknesses, [110, 110, 220, 220, 220, 220])

        total_openings = sum(len(w.openings) for w in walls)
        self.assertEqual(total_openings, 5)

    def test_opening_widths_match_the_drawing(self):
        from roomgraph.pdf.content import read_pdf

        geo = read_pdf(plan("apartment.pdf"))
        walls = extract_walls(geo, determine_scale(geo).mm_per_pt)
        widths = sorted(round(o.width) for w in walls for o in w.openings)
        self.assertEqual(widths, [800, 900, 1000, 1200, 1500])

    def test_furniture_does_not_become_a_wall(self):
        """Sofa and bed rectangles sit on A-FURN and are far too thick to pair."""
        from roomgraph.pdf.content import read_pdf

        geo = read_pdf(plan("apartment.pdf"))
        walls = extract_walls(geo, determine_scale(geo).mm_per_pt)
        self.assertTrue(all(w.layer == "A-WALL" for w in walls))


class TestArrangement(unittest.TestCase):
    def test_t_junction_is_split(self):
        """A partition ending against a party wall must divide it."""
        walls = [
            Wall(Pt(0, 0), Pt(1000, 0), 100),
            Wall(Pt(1000, 0), Pt(1000, 1000), 100),
            Wall(Pt(1000, 1000), Pt(0, 1000), 100),
            Wall(Pt(0, 1000), Pt(0, 0), 100),
            Wall(Pt(500, 0), Pt(500, 1000), 100),
        ]
        arr = build_arrangement(walls)
        self.assertEqual(len(arr.inner_faces()), 2)

    def test_dangling_stub_is_pruned(self):
        walls = [
            Wall(Pt(0, 0), Pt(1000, 0), 100),
            Wall(Pt(1000, 0), Pt(1000, 1000), 100),
            Wall(Pt(1000, 1000), Pt(0, 1000), 100),
            Wall(Pt(0, 1000), Pt(0, 0), 100),
            Wall(Pt(500, 1000), Pt(500, 1400), 100),  # stub into nothing
        ]
        arr = build_arrangement(walls)
        self.assertEqual(len(arr.inner_faces()), 1)

    def test_outer_face_has_negative_area(self):
        walls = [
            Wall(Pt(0, 0), Pt(1000, 0), 100),
            Wall(Pt(1000, 0), Pt(1000, 1000), 100),
            Wall(Pt(1000, 1000), Pt(0, 1000), 100),
            Wall(Pt(0, 1000), Pt(0, 0), 100),
        ]
        arr = build_arrangement(walls)
        self.assertEqual(sum(1 for f in arr.faces if f.is_outer), 1)

    def test_no_walls_gives_no_faces(self):
        self.assertEqual(build_arrangement([]).faces, [])


class TestClassification(unittest.TestCase):
    def test_vietnamese_with_diacritics(self):
        self.assertEqual(classify("PHÒNG NGỦ"), "bedroom")
        self.assertEqual(classify("Phòng khách"), "living")
        self.assertEqual(classify("BẾP"), "kitchen")
        self.assertEqual(classify("WC"), "bathroom")
        self.assertEqual(classify("Ban công"), "balcony")

    def test_english(self):
        self.assertEqual(classify("Master Bedroom"), "bedroom")
        self.assertEqual(classify("Kitchen"), "kitchen")

    def test_unknown_and_empty(self):
        self.assertEqual(classify(None), "unknown")
        self.assertEqual(classify("Zzzz"), "other")


class TestApartmentEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("apartment.pdf"))
        cls.truth = ground_truth()[0]

    def test_scale_is_recovered_from_dimensions(self):
        self.assertEqual(self.model.scale.source, "dimension")
        self.assertAlmostEqual(self.model.scale.drawing_scale, 50.0, places=1)

    def test_room_count(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])

    def test_room_areas_match_ground_truth(self):
        got = sorted(r.area_gross_m2 for r in self.model.rooms)
        want = sorted(r["area_gross_m2"] for r in self.truth["rooms"])
        for a, b in zip(got, want, strict=False):
            self.assertAlmostEqual(a, b, places=1)

    def test_room_names_and_categories(self):
        by_name = {r.name: r for r in self.model.rooms}
        self.assertEqual(by_name["PHONG KHACH"].category, "living")
        self.assertEqual(by_name["PHONG NGU"].category, "bedroom")
        self.assertEqual(by_name["BEP"].category, "kitchen")

    def test_net_area_is_smaller_than_gross(self):
        for r in self.model.rooms:
            self.assertLess(r.area_net_m2, r.area_gross_m2)
            self.assertGreater(r.area_net_m2, 0.8 * r.area_gross_m2)

    def test_printed_areas_agree(self):
        for r in self.model.rooms:
            self.assertEqual(r.area_check(), "ok", f"{r.name} area disagrees with its label")

    def test_opening_counts(self):
        counts = self.model.counts()
        self.assertEqual(counts.get("door"), self.truth["doors"])
        self.assertEqual(counts.get("window"), self.truth["windows"])

    def test_every_opening_matched_a_symbol(self):
        for op in self.model.openings:
            self.assertIsNotNone(op.symbol, f"{op.kind} opening matched nothing")
            self.assertGreater(op.confidence, 0.5)

    def test_adjacency_matches_ground_truth(self):
        by_id = {r.id: r.name for r in self.model.rooms}
        got = {
            frozenset((by_id[e.a], by_id[e.b])): e.kind
            for e in self.model.graph.edges
        }
        for a, b, kind in self.truth["adjacency"]:
            with self.subTest(pair=(a, b)):
                self.assertEqual(got.get(frozenset((a, b))), kind)

    def test_graph_is_walkable(self):
        self.assertTrue(self.model.graph.is_connected())

    def test_entrance_is_found(self):
        self.assertEqual(len(self.model.graph.entrances), 1)
        self.assertEqual(self.model.graph.entrances[0].kind, "door")

    def test_windows_to_outside_are_not_entrances(self):
        kinds = {c.kind for c in self.model.graph.exterior}
        self.assertIn("window", kinds)
        self.assertTrue(all(c.kind != "window" for c in self.model.graph.entrances))

    def test_no_warnings_on_a_clean_plan(self):
        self.assertEqual(self.model.warnings, [])

    def test_explicit_scale_overrides_detection(self):
        m = extract(plan("apartment.pdf"), scale="17.638889mm")
        self.assertEqual(m.scale.source, "explicit")
        self.assertAlmostEqual(m.total_area_m2, self.model.total_area_m2, places=1)

    def test_a_wrong_scale_warns_rather_than_inventing_rooms(self):
        """At 1:100 the 220 mm exterior walls measure 440 mm, past the wall
        ceiling, so the envelope never pairs and nothing encloses. The failure
        must be loud -- a silent empty model is the worst outcome here."""
        m = extract(plan("apartment.pdf"), scale="1:100")
        self.assertEqual(m.rooms, [])
        self.assertTrue(
            any("no rooms found" in w for w in m.warnings),
            f"expected a loud warning, got {m.warnings}",
        )


class TestStudioEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("studio_lshape.pdf"))
        cls.truth = ground_truth()[1]

    def test_room_count(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])

    def test_l_shaped_room_area(self):
        main = max(self.model.rooms, key=lambda r: r.area_gross_m2)
        self.assertAlmostEqual(main.area_gross_m2, 30.52, places=1)

    def test_label_point_is_inside_the_l(self):
        from roomgraph.geom import point_in_polygon

        for r in self.model.rooms:
            self.assertTrue(point_in_polygon(r.label_point, r.polygon))

    def test_wc_is_classified(self):
        wc = min(self.model.rooms, key=lambda r: r.area_gross_m2)
        self.assertEqual(wc.category, "bathroom")

    def test_two_doors(self):
        self.assertEqual(self.model.counts().get("door"), self.truth["doors"])


if __name__ == "__main__":
    unittest.main()
