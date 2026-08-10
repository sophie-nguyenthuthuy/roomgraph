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
    bridge_corners,
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


class TestBayWindowEndToEnd(unittest.TestCase):
    """The bay symbol, through the real pipeline rather than a synthetic context.

    Its geometry sits *outside* the wall line, so this is what proves the local
    frame and the stroke-gathering reach actually deliver it to the detector.
    """

    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("bay_house.pdf"))
        cls.truth = ground_truth()[2]

    def _bay(self):
        return next(op for op in self.model.openings if op.symbol == "window_bay")

    def test_the_bay_is_recognised(self):
        symbols = [op.symbol for op in self.model.openings]
        self.assertIn("window_bay", symbols)
        self.assertEqual(symbols.count("window_bay"), 1)

    def test_bay_beats_the_flat_window_symbol(self):
        bay = self._bay()
        self.assertEqual(bay.kind, "window")
        self.assertGreater(bay.confidence, 0.7)

    def test_bay_geometry_is_recovered(self):
        bay = self._bay()
        want = self.truth["bay"]
        self.assertEqual(bay.meta["style"], want["style"])
        self.assertEqual(bay.meta["facets"], want["facets"])
        self.assertAlmostEqual(bay.width, want["width_mm"], delta=5.0)
        self.assertAlmostEqual(bay.meta["projection_mm"], want["projection_mm"], delta=5.0)

    def test_doors_are_unaffected(self):
        self.assertEqual(self.model.counts().get("door"), self.truth["doors"])

    def test_rooms_still_come_out(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])

    def test_the_bay_does_not_leak_into_the_room_polygon(self):
        """The projection is outside the envelope; room areas must ignore it."""
        for r in self.model.rooms:
            self.assertLess(r.area_gross_m2, 30.0)

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestCornerBridging(unittest.TestCase):
    """Corner reconstruction, in isolation.

    A corner window deletes the corner, so both walls stop short and the room
    never encloses. Bridging puts it back -- but it must stay asleep for every
    ordinary junction, or it would invent walls that were never drawn.
    """

    def _open_corner(self):
        return [
            Wall(Pt(0, 0), Pt(5000, 0), 200),
            Wall(Pt(5000, 0), Pt(5000, 4000), 200),
            Wall(Pt(5000, 4000), Pt(1500, 4000), 200),   # stops short
            Wall(Pt(0, 2500), Pt(0, 0), 200),            # stops short
        ]

    def test_a_missing_corner_is_rebuilt(self):
        walls = bridge_corners(self._open_corner())
        top = walls[2]
        left = walls[3]
        self.assertAlmostEqual(top.b.x, 0.0, places=6)
        self.assertAlmostEqual(top.b.y, 4000.0, places=6)
        self.assertAlmostEqual(left.a.x, 0.0, places=6)
        self.assertAlmostEqual(left.a.y, 4000.0, places=6)

    def test_the_invented_length_is_recorded_as_an_opening(self):
        walls = bridge_corners(self._open_corner())
        bridged = [o for w in walls for o in w.openings if o.bridged]
        self.assertEqual(len(bridged), 2)
        self.assertAlmostEqual(bridged[0].width, 1500.0, places=6)
        self.assertAlmostEqual(bridged[1].width, 1500.0, places=6)

    def test_the_room_now_encloses(self):
        arr = build_arrangement(bridge_corners(self._open_corner()))
        self.assertEqual(len(arr.inner_faces()), 1)
        self.assertAlmostEqual(arr.inner_faces()[0].area / 1e6, 20.0, places=2)

    def test_without_bridging_the_room_is_lost(self):
        arr = build_arrangement(self._open_corner())
        self.assertEqual(arr.inner_faces(), [])

    def test_an_ordinary_closed_corner_is_left_alone(self):
        walls = [
            Wall(Pt(0, 0), Pt(5000, 0), 200),
            Wall(Pt(5000, 0), Pt(5000, 4000), 200),
            Wall(Pt(5000, 4000), Pt(0, 4000), 200),
            Wall(Pt(0, 4000), Pt(0, 0), 200),
        ]
        before = [(w.a, w.b) for w in walls]
        bridge_corners(walls)
        self.assertEqual([(w.a, w.b) for w in walls], before)
        self.assertEqual([o for w in walls for o in w.openings], [])

    def test_a_t_junction_end_is_not_a_free_end(self):
        walls = [
            Wall(Pt(0, 0), Pt(5000, 0), 200),
            Wall(Pt(2500, 0), Pt(2500, 3000), 100),  # tee into the first wall
        ]
        bridge_corners(walls)
        self.assertEqual([o for w in walls for o in w.openings], [])

    def test_parallel_walls_are_never_bridged(self):
        walls = [
            Wall(Pt(0, 0), Pt(2000, 0), 200),
            Wall(Pt(3000, 0), Pt(5000, 0), 200),
        ]
        bridge_corners(walls)
        self.assertEqual([o for w in walls for o in w.openings], [])

    def test_a_corner_further_than_the_leg_limit_is_refused(self):
        walls = [
            Wall(Pt(0, 0), Pt(5000, 0), 200),
            Wall(Pt(9000, 4000), Pt(9000, 9000), 200),  # corner 4 m / 4 m away
        ]
        bridge_corners(walls)
        self.assertEqual([o for w in walls for o in w.openings], [])

    def test_bridging_does_not_disturb_the_ordinary_fixtures(self):
        model = extract(plan("apartment.pdf"))
        self.assertEqual(len(model.rooms), 3)
        self.assertFalse([o for o in model.openings if o.bridged])


class TestCornerWindowEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("corner_window.pdf"))
        cls.truth = ground_truth()[3]

    def test_the_room_survives_the_missing_corner(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])
        self.assertAlmostEqual(
            self.model.rooms[0].area_gross_m2, self.truth["rooms"][0]["area_gross_m2"], places=1
        )

    def test_both_legs_are_recognised(self):
        corners = [op for op in self.model.openings if op.symbol == "window_corner"]
        self.assertEqual(len(corners), self.truth["corner_window"]["openings"])
        for op in corners:
            self.assertEqual(op.kind, "window")
            self.assertTrue(op.bridged)
            self.assertAlmostEqual(op.width, self.truth["corner_window"]["leg_mm"], delta=5.0)

    def test_it_beats_the_plain_opening_fallback(self):
        for op in self.model.openings:
            if op.bridged:
                self.assertGreater(op.confidence, 0.8)

    def test_the_door_is_unaffected(self):
        self.assertEqual(self.model.counts().get("door"), self.truth["doors"])

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestFoldingDoorEndToEnd(unittest.TestCase):
    """A folding door on a *diagonal* wall.

    Every other fixture is axis aligned, so this is what actually proves the
    local frame works at an angle: the zigzag is only a zigzag once the wall
    direction has been rotated out.
    """

    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("folding_door.pdf"))
        cls.truth = ground_truth()[4]

    def test_the_diagonal_partition_divides_the_plan(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])
        for room, want in zip(
            sorted(self.model.rooms, key=lambda r: r.area_gross_m2),
            sorted(self.truth["rooms"], key=lambda r: r["area_gross_m2"]),
            strict=True,
        ):
            self.assertAlmostEqual(room.area_gross_m2, want["area_gross_m2"], places=1)

    def test_the_folding_door_is_recognised_at_an_angle(self):
        folds = [op for op in self.model.openings if op.symbol == "door_folding"]
        self.assertEqual(len(folds), 1)
        want = self.truth["folding_door"]
        self.assertEqual(folds[0].kind, "door")
        self.assertEqual(folds[0].meta["panels"], want["panels"])
        self.assertAlmostEqual(folds[0].width, want["width_mm"], delta=5.0)
        self.assertAlmostEqual(
            folds[0].meta["leaf_width_mm"], want["leaf_width_mm"], delta=15.0
        )

    def test_it_beats_the_swing_and_plain_fallbacks(self):
        fold = next(op for op in self.model.openings if op.symbol == "door_folding")
        self.assertGreater(fold.confidence, 0.8)

    def test_the_rooms_are_connected_through_it(self):
        self.assertTrue(self.model.graph.is_connected())
        kinds = {e.kind for e in self.model.graph.edges}
        self.assertIn("door", kinds)

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestRevolvingDoorEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("revolving_lobby.pdf"))
        cls.truth = ground_truth()[5]

    def _revolving(self):
        return next(op for op in self.model.openings if op.symbol == "door_revolving")

    def test_the_wheel_is_recognised(self):
        want = self.truth["revolving_door"]
        rev = self._revolving()
        self.assertEqual(rev.kind, "door")
        self.assertEqual(rev.meta["panels"], want["panels"])
        self.assertIs(rev.meta["drum_drawn"], want["drum_drawn"])
        self.assertAlmostEqual(rev.width, want["drum_diameter_mm"], delta=5.0)
        self.assertGreater(rev.confidence, 0.8)

    def test_the_swing_door_beside_it_is_still_a_swing(self):
        swings = [op for op in self.model.openings if op.symbol == "door_swing"]
        self.assertEqual(len(swings), 1)
        self.assertGreater(swings[0].confidence, self._revolving().confidence * 0.8)

    def test_counts_match(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])
        self.assertEqual(self.model.counts().get("door"), self.truth["doors"])

    def test_the_revolving_door_is_the_entrance(self):
        entrances = self.model.graph.entrances
        self.assertEqual(len(entrances), 1)
        self.assertEqual(entrances[0].symbol, "door_revolving")

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestCommercialUnitEndToEnd(unittest.TestCase):
    """Curtain walling, a roller shutter and a lift car in one plan."""

    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("commercial_unit.pdf"))
        cls.truth = ground_truth()[6]

    def test_a_six_metre_glazed_run_survives(self):
        want = self.truth["curtain_wall"]
        cw = next(op for op in self.model.openings if op.symbol == "curtain_wall")
        self.assertEqual(cw.kind, "window")
        self.assertAlmostEqual(cw.width, want["run_mm"], delta=10.0)
        self.assertEqual(cw.meta["mullions"], want["mullions"])
        self.assertAlmostEqual(cw.meta["module_mm"], 1200.0, delta=15.0)

    def test_curtain_walling_beats_a_plain_window(self):
        cw = next(op for op in self.model.openings if op.symbol == "curtain_wall")
        self.assertGreater(cw.confidence, 0.9)

    def test_the_roller_shutter_is_recognised(self):
        want = self.truth["roller_shutter"]
        rs = next(op for op in self.model.openings if op.symbol == "door_roller")
        self.assertEqual(rs.kind, "door")
        self.assertTrue(rs.meta["corrugated"])
        self.assertAlmostEqual(rs.width, want["clear_width_mm"], delta=10.0)

    def test_the_lift_car_is_found_in_its_shaft(self):
        lifts = [f for f in self.model.features if f.symbol == "lift"]
        self.assertEqual(len(lifts), 1)
        self.assertEqual(lifts[0].meta["diagonals"], 2)
        for got, want in zip(lifts[0].meta["car_mm"], self.truth["lift"]["car_mm"], strict=True):
            self.assertAlmostEqual(got, want, delta=10.0)

    def test_room_count(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestServicesEndToEnd(unittest.TestCase):
    """Two room-scope symbols, each reporting on its own room."""

    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("services.pdf"))
        cls.truth = ground_truth()[7]

    def test_sanitary_fittings_are_catalogued(self):
        sanitary = [f for f in self.model.features if f.symbol == "sanitary"]
        self.assertEqual(len(sanitary), 1, "only the bathroom should report fittings")
        self.assertEqual(
            sorted(sanitary[0].meta["fittings"]), self.truth["sanitary"]["fittings"]
        )

    def test_the_spiral_stair_is_recognised(self):
        want = self.truth["spiral"]
        spirals = [f for f in self.model.features if f.symbol == "stairs_spiral"]
        self.assertEqual(len(spirals), 1)
        self.assertEqual(spirals[0].meta["treads"], want["treads"])
        self.assertAlmostEqual(spirals[0].meta["radius_mm"], want["radius_mm"], delta=10.0)
        self.assertAlmostEqual(spirals[0].meta["sweep_deg"], 360.0, delta=2.0)

    def test_the_straight_flight_symbol_does_not_fire(self):
        self.assertFalse([f for f in self.model.features if f.symbol == "stairs"])

    def test_features_are_attributed_to_the_right_rooms(self):
        by_room = {f.symbol: f.room for f in self.model.features}
        bathroom = next(r for r in self.model.rooms if r.category == "bathroom")
        self.assertEqual(by_room["sanitary"], bathroom.id)
        self.assertNotEqual(by_room["stairs_spiral"], bathroom.id)

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestFittedFlatEndToEnd(unittest.TestCase):
    """Kitchen run, columns and an accessible WC -- three room symbols that all
    look like small rectangles until you ask the right question of them."""

    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("fitted_flat.pdf"))
        cls.truth = ground_truth()[8]

    def _features(self, symbol: str):
        return [f for f in self.model.features if f.symbol == symbol]

    def test_the_kitchen_run_is_measured(self):
        want = self.truth["kitchen"]
        runs = self._features("kitchen")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].meta["units"], want["units"])
        self.assertAlmostEqual(runs[0].meta["depth_mm"], want["depth_mm"], delta=5.0)

    def test_kitchen_units_are_not_reported_as_basins(self):
        kitchen_room = self._features("kitchen")[0].room
        for f in self._features("sanitary"):
            self.assertNotEqual(f.room, kitchen_room)

    def test_kitchen_units_are_not_reported_as_columns(self):
        kitchen_room = self._features("kitchen")[0].room
        for f in self._features("column"):
            self.assertNotEqual(f.room, kitchen_room)

    def test_columns_are_found_and_the_poche_one_is_seen(self):
        want = self.truth["columns"]
        cols = self._features("column")
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0].meta["columns"], want["columns"])
        self.assertEqual(cols[0].meta["filled"], want["filled"])

    def test_columns_are_not_reported_as_a_kitchen(self):
        column_room = self._features("column")[0].room
        for f in self._features("kitchen"):
            self.assertNotEqual(f.room, column_room)

    def test_the_turning_circle_is_clear(self):
        circles = self._features("turning_circle")
        self.assertEqual(len(circles), 1)
        self.assertAlmostEqual(
            circles[0].meta["diameter_mm"], self.truth["turning_circle"]["diameter_mm"], delta=5.0
        )

    def test_the_wc_reports_both_its_pan_and_its_circle(self):
        wc = self._features("turning_circle")[0].room
        self.assertIn(wc, [f.room for f in self._features("sanitary")])

    def test_room_count(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestTransportHallEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("transport_hall.pdf"))
        cls.truth = ground_truth()[9]

    def _features(self, symbol: str):
        return [f for f in self.model.features if f.symbol == symbol]

    def test_the_escalator_is_recognised(self):
        want = self.truth["escalator"]
        esc = self._features("escalator")
        self.assertEqual(len(esc), 1)
        self.assertEqual(esc[0].meta["steps"], want["steps"])
        self.assertAlmostEqual(esc[0].meta["going_mm"], want["going_mm"], delta=5.0)
        self.assertGreaterEqual(esc[0].meta["balustrades"], 2)

    def test_the_straight_flight_symbol_stands_down(self):
        self.assertFalse(self._features("stairs"))

    def test_the_ramp_is_read_from_its_gradient_label(self):
        ramps = self._features("ramp")
        self.assertEqual(len(ramps), 1)
        self.assertEqual(ramps[0].meta["gradient"], self.truth["ramp"]["gradient"])

    def test_the_ramp_measures_its_own_band_not_the_escalator(self):
        ramp = self._features("ramp")[0]
        self.assertAlmostEqual(ramp.meta["width_mm"], 2400.0, delta=20.0)
        self.assertAlmostEqual(ramp.meta["length_mm"], 11000.0, delta=20.0)

    def test_the_fire_shutter_outranks_a_plain_roller(self):
        want = self.truth["fire_shutter"]
        fs = next(op for op in self.model.openings if op.symbol == "door_fire_shutter")
        self.assertTrue(fs.meta["rated"])
        self.assertIn("FIRE", fs.meta["fire_layer"].upper())
        self.assertAlmostEqual(fs.width, want["clear_width_mm"], delta=10.0)

    def test_escalator_and_ramp_share_a_room(self):
        self.assertEqual(self._features("escalator")[0].room, self._features("ramp")[0].room)

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


class TestDwellingEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("dwelling.pdf"))
        cls.truth = ground_truth()[10]

    def _f(self, symbol):
        return [f for f in self.model.features if f.symbol == symbol]

    def test_the_bed_and_desk_are_read(self):
        want = self.truth["furniture"]
        got = self._f("furniture_layout")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["beds"], want["beds"])
        self.assertEqual(sorted(got[0].meta["items"]), want["items"])

    def test_the_desk_depends_on_the_room_being_a_bedroom(self):
        room_id = self._f("furniture_layout")[0].room
        room = next(r for r in self.model.rooms if r.id == room_id)
        self.assertEqual(room.category, "bedroom")

    def test_the_planting_is_scalloped_not_circular(self):
        got = self._f("planting")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["canopies"], self.truth["planting"]["canopies"])

    def test_planting_is_not_reported_as_a_turning_circle(self):
        self.assertFalse(self._f("turning_circle"))

    def test_the_dumbwaiter_is_too_small_to_be_a_lift(self):
        got = self._f("dumbwaiter")
        self.assertEqual(len(got), 1)
        for a, b in zip(got[0].meta["car_mm"], self.truth["dumbwaiter"]["car_mm"], strict=True):
            self.assertAlmostEqual(a, b, delta=10.0)
        self.assertFalse(self._f("lift"))

    def test_room_count_and_no_warnings(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])
        self.assertEqual(self.model.warnings, [])


class TestConcourseEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("concourse.pdf"))
        cls.truth = ground_truth()[11]

    def _f(self, symbol):
        return [f for f in self.model.features if f.symbol == symbol]

    def test_the_travelator_measures_its_own_band(self):
        want = self.truth["travelator"]
        got = self._f("travelator")
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0].meta["width_mm"], want["width_mm"], delta=20.0)
        self.assertAlmostEqual(got[0].meta["run_mm"], want["run_mm"], delta=50.0)
        self.assertGreater(got[0].meta["pallets"], 20)

    def test_the_escalator_stands_down_for_a_run_that_long(self):
        self.assertFalse(self._f("escalator"))
        self.assertFalse(self._f("stairs"))

    def test_fire_equipment_is_found_by_its_layer(self):
        got = self._f("fire_equipment")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["items"], self.truth["fire_equipment"]["items"])
        self.assertTrue(got[0].meta["layers"])

    def test_the_parking_bays_are_counted(self):
        got = self._f("parking_bay")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["bays"], self.truth["parking"]["bays"])

    def test_parking_bays_are_not_read_as_arcs(self):
        """A rectangle's corners are concyclic, so a coarse circle fit calls
        every bay a perfect arc -- which used to silence `opening_plain`."""
        for op in self.model.openings:
            self.assertIsNotNone(op.symbol)

    def test_room_count_and_no_warnings(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])
        self.assertEqual(self.model.warnings, [])


class TestInstitutionEndToEnd(unittest.TestCase):
    """The four specialised symbols, one per room."""

    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("institution.pdf"))
        cls.truth = ground_truth()[12]

    def _f(self, symbol):
        return [f for f in self.model.features if f.symbol == symbol]

    def test_the_rooms_are_classified(self):
        self.assertEqual(len(self.model.rooms), self.truth["room_count"])
        self.assertEqual(
            sorted(r.category for r in self.model.rooms),
            ["auditorium", "lab", "technical", "ward"],
        )

    def test_lab_benching(self):
        want = self.truth["lab_bench"]
        got = self._f("lab_bench")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["wall_benches"], want["wall_benches"])
        self.assertEqual(got[0].meta["islands"], want["islands"])

    def test_benching_is_not_found_in_the_plant_room(self):
        plant_room = self._f("plant_equipment")[0].room
        for f in self._f("lab_bench"):
            self.assertNotEqual(f.room, plant_room)

    def test_ward_bays(self):
        want = self.truth["ward"]
        got = self._f("ward_bay")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["bays"], want["bays"])
        self.assertAlmostEqual(got[0].meta["bay_pitch_mm"], want["bay_pitch_mm"], delta=20.0)

    def test_the_ward_also_reports_its_beds(self):
        """Room features accumulate: the ward is the room, the beds its
        contents, and both statements are true and separately useful."""
        ward = self._f("ward_bay")[0]
        furniture = [f for f in self._f("furniture_layout") if f.room == ward.room]
        self.assertEqual(len(furniture), 1)
        self.assertEqual(furniture[0].meta["beds"], self.truth["ward"]["bays"])
        self.assertGreaterEqual(ward.confidence, furniture[0].confidence)

    def test_theatre_seating(self):
        want = self.truth["seating"]
        got = self._f("theatre_seating")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["seats"], want["seats"])
        self.assertEqual(got[0].meta["rows"], want["rows"])
        self.assertAlmostEqual(got[0].meta["row_pitch_mm"], want["row_pitch_mm"], delta=20.0)

    def test_seats_are_not_reported_as_columns(self):
        self.assertFalse(self._f("column"))

    def test_plant_equipment_is_found_by_layer_and_label(self):
        got = self._f("plant_equipment")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].meta["items"], self.truth["plant"]["items"])
        self.assertTrue(got[0].meta["layers"])
        self.assertEqual(got[0].meta["label"], "AHU-01")

    def test_no_warnings(self):
        self.assertEqual(self.model.warnings, [])


if __name__ == "__main__":
    unittest.main()
