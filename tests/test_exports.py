"""Exports must be parseable by something other than this project."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

from support import plan

from roomgraph.export import anim, geojson, ifc, json_model, svg
from roomgraph.export.raster import Canvas, lzw_encode, mix, quantise, write_gif
from roomgraph.model import extract


class ExportBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = extract(plan("apartment.pdf"))


class TestJson(ExportBase):
    def test_roundtrips_through_json(self):
        doc = json.loads(json_model.dumps(self.model))
        self.assertTrue(doc["schema"].startswith("roomgraph/"))
        self.assertEqual(len(doc["rooms"]), 3)
        self.assertEqual(doc["units"], {"length": "mm", "area": "m2"})

    def test_every_room_has_a_closed_polygon(self):
        doc = json_model.to_dict(self.model)
        for room in doc["rooms"]:
            self.assertGreaterEqual(len(room["polygon_mm"]), 4)
            for pair in room["polygon_mm"]:
                self.assertEqual(len(pair), 2)

    def test_openings_reference_real_walls(self):
        doc = json_model.to_dict(self.model)
        wall_ids = {w["id"] for w in doc["walls"]}
        for op in doc["openings"]:
            self.assertIn(op["wall"], wall_ids)

    def test_graph_edges_reference_real_rooms(self):
        doc = json_model.to_dict(self.model)
        ids = {r["id"] for r in doc["rooms"]}
        for e in doc["graph"]["edges"]:
            self.assertIn(e["a"], ids)
            self.assertIn(e["b"], ids)

    def test_wall_opening_ids_resolve(self):
        doc = json_model.to_dict(self.model)
        opening_ids = {o["id"] for o in doc["openings"]}
        for w in doc["walls"]:
            for oid in w["openings"]:
                self.assertIn(oid, opening_ids)

    def test_scale_is_reported_with_provenance(self):
        doc = json_model.to_dict(self.model)
        self.assertIn("source", doc["scale"])
        self.assertIn("confidence", doc["scale"])


class TestGeoJson(ExportBase):
    def test_structure(self):
        doc = json.loads(geojson.dumps(self.model))
        self.assertEqual(doc["type"], "FeatureCollection")
        self.assertTrue(doc["features"])
        for f in doc["features"]:
            self.assertEqual(f["type"], "Feature")
            self.assertIn(f["geometry"]["type"], ("Polygon", "LineString", "Point"))

    def test_polygons_are_closed_rings(self):
        doc = geojson.to_dict(self.model, include=("rooms",))
        for f in doc["features"]:
            ring = f["geometry"]["coordinates"][0]
            self.assertEqual(ring[0], ring[-1], "GeoJSON rings must close")

    def test_local_metres_are_declared_not_faked(self):
        doc = geojson.to_dict(self.model)
        self.assertIn("local engineering grid", doc["roomgraph:crs"])

    def test_geo_origin_produces_plausible_lon_lat(self):
        doc = geojson.to_dict(self.model, geo_origin=(21.0278, 105.8342))
        self.assertEqual(doc["roomgraph:crs"], "EPSG:4326")
        lon, lat = doc["features"][0]["geometry"]["coordinates"][0][0]
        self.assertAlmostEqual(lon, 105.8342, places=2)
        self.assertAlmostEqual(lat, 21.0278, places=2)

    def test_include_filter(self):
        doc = geojson.to_dict(self.model, include=("walls",))
        kinds = {f["properties"]["layer"] for f in doc["features"]}
        self.assertEqual(kinds, {"wall"})


class TestIfc(ExportBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.text = ifc.export(cls.model)

    def test_header_and_footer(self):
        self.assertTrue(self.text.startswith("ISO-10303-21;"))
        self.assertIn("FILE_SCHEMA(('IFC4'));", self.text)
        self.assertTrue(self.text.rstrip().endswith("END-ISO-10303-21;"))

    def test_spatial_hierarchy_present(self):
        for entity in ("IFCPROJECT(", "IFCSITE(", "IFCBUILDING(", "IFCBUILDINGSTOREY("):
            self.assertIn(entity, self.text)

    def test_one_space_per_room(self):
        self.assertEqual(self.text.count("IFCSPACE("), len(self.model.rooms))

    def test_walls_doors_windows(self):
        self.assertEqual(self.text.count("IFCWALLSTANDARDCASE("), len(self.model.walls))
        self.assertEqual(self.text.count("IFCDOOR("), 3)
        self.assertEqual(self.text.count("IFCWINDOW("), 2)

    def test_every_opening_is_voided_and_filled(self):
        n = len(self.model.openings)
        self.assertEqual(self.text.count("IFCOPENINGELEMENT("), n)
        self.assertEqual(self.text.count("IFCRELVOIDSELEMENT("), n)
        self.assertEqual(self.text.count("IFCRELFILLSELEMENT("), n)

    def test_entity_ids_are_dense_and_ordered(self):
        ids = [int(m) for m in re.findall(r"^#(\d+)= ", self.text, re.M)]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_every_reference_resolves(self):
        defined = {int(m) for m in re.findall(r"^#(\d+)= ", self.text, re.M)}
        used = {int(m) for m in re.findall(r"#(\d+)", self.text)}
        self.assertEqual(used - defined, set(), "dangling entity references")

    def test_guids_are_22_chars_and_deterministic(self):
        guids = re.findall(r"'([0-9A-Za-z_$]{22})'", self.text)
        self.assertTrue(guids)
        self.assertEqual(ifc.export(self.model), self.text, "export must be reproducible")

    def test_quantities_carry_the_measured_areas(self):
        for r in self.model.rooms:
            self.assertIn(f"{r.area_net_m2:.6f}".rstrip("0").rstrip("."), self.text)

    def test_apostrophes_in_names_are_escaped(self):
        model = extract(plan("apartment.pdf"))
        model.rooms[0].name = "Bill's Room"
        text = ifc.export(model)
        self.assertIn("Bill\\'s Room", text)

    def test_non_ascii_names_do_not_corrupt_the_file(self):
        model = extract(plan("apartment.pdf"))
        model.rooms[0].name = "PHÒNG NGỦ"
        text = ifc.export(model)
        text.encode("ascii")  # SPF is ASCII; must not raise


class TestSvg(ExportBase):
    def test_is_well_formed_xml(self):
        root = ET.fromstring(svg.render(self.model))
        self.assertTrue(root.tag.endswith("svg"))

    def test_has_a_polygon_per_room(self):
        root = ET.fromstring(svg.render(self.model))
        polys = root.findall(".//{http://www.w3.org/2000/svg}polygon")
        self.assertEqual(len(polys), len(self.model.rooms))

    def test_graph_layer_can_be_switched_off(self):
        with_graph = svg.render(self.model, show_graph=True)
        without = svg.render(self.model, show_graph=False)
        self.assertIn('id="graph"', with_graph)
        self.assertNotIn('id="graph"', without)

    def test_room_names_appear(self):
        text = svg.render(self.model)
        for r in self.model.rooms:
            self.assertIn(r.name, text)

    def test_special_characters_are_escaped(self):
        model = extract(plan("apartment.pdf"))
        model.rooms[0].name = 'A & B <c> "d"'
        out = svg.render(model)
        ET.fromstring(out)  # must still parse
        self.assertIn("&amp;", out)


class TestRaster(unittest.TestCase):
    def test_mix_endpoints(self):
        self.assertEqual(mix((0, 0, 0), (255, 255, 255), 0.0), (0, 0, 0))
        self.assertEqual(mix((0, 0, 0), (255, 255, 255), 1.0), (255, 255, 255))
        self.assertEqual(mix((0, 0, 0), (100, 100, 100), 0.5), (50, 50, 50))

    def test_polygon_fill_covers_interior(self):
        c = Canvas(20, 20, (255, 255, 255))
        c.fill_polygon([(5, 5), (15, 5), (15, 15), (5, 15)], (0, 0, 0))
        i = (10 * 20 + 10) * 3
        self.assertEqual(bytes(c.buf[i : i + 3]), b"\x00\x00\x00")
        j = (2 * 20 + 2) * 3
        self.assertEqual(bytes(c.buf[j : j + 3]), b"\xff\xff\xff")

    def test_drawing_outside_bounds_is_clipped(self):
        c = Canvas(10, 10)
        c.fill_polygon([(-100, -100), (200, -100), (200, 200), (-100, 200)], (1, 2, 3))
        c.fill_circle(-50, -50, 10, (9, 9, 9))
        self.assertEqual(len(c.buf), 300)

    def test_quantise_keeps_small_palettes_exact(self):
        c = Canvas(4, 4, (10, 20, 30))
        c.fill_polygon([(0, 0), (2, 0), (2, 2), (0, 2)], (200, 100, 50))
        palette, frames = quantise([c])
        self.assertLessEqual(len(palette), 256)
        self.assertIn((10, 20, 30), palette)
        self.assertIn((200, 100, 50), palette)

    def test_quantise_caps_the_palette(self):
        c = Canvas(40, 40)
        for i in range(40):
            for j in range(40):
                c.pixel(i, j, (i * 6 % 256, j * 6 % 256, (i + j) % 256))
        palette, _ = quantise([c], max_colours=16)
        self.assertLessEqual(len(palette), 16)

    def test_lzw_output_starts_with_a_clear_code(self):
        out = lzw_encode(b"\x00\x00\x01", 8)
        self.assertTrue(out)
        first = out[0] | ((out[1] & 0x01) << 8)
        self.assertEqual(first, 256)

    def test_lzw_handles_empty_input(self):
        self.assertTrue(lzw_encode(b"", 8))


class TestGif(ExportBase):
    def test_gif_decodes_back_to_the_source_pixels(self):
        """Encode two frames, decode with an independent LZW reader, compare."""
        a = Canvas(24, 16, (255, 255, 255))
        a.fill_polygon([(2, 2), (20, 2), (20, 12), (2, 12)], (200, 30, 40))
        b = Canvas(24, 16, (255, 255, 255))
        b.fill_circle(12, 8, 5, (10, 90, 200))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.gif")
            write_gif(path, [a, b], [5, 5])
            with open(path, "rb") as fh:
                data = fh.read()

        self.assertEqual(data[:6], b"GIF89a")
        self.assertEqual(data[-1:], b"\x3b")
        self.assertIn(b"NETSCAPE2.0", data)

        palette, frames = _decode_gif(data)
        self.assertEqual(len(frames), 2)
        for canvas, indices in zip((a, b), frames, strict=False):
            rgb = b"".join(bytes(palette[i]) for i in indices)
            self.assertEqual(rgb, bytes(canvas.buf))

    def test_storyboard_frames_are_uniform(self):
        frames, delays = anim.storyboard(self.model, width=160, height=120)
        self.assertGreater(len(frames), 20)
        self.assertEqual(len(frames), len(delays))
        self.assertTrue(all(f.w == 160 and f.h == 120 for f in frames))

    def test_a_hatched_plan_gains_a_materials_beat(self):
        """The animation draws the detector's own rulings, so a plan with
        hatch shows its materials and one without is unchanged."""
        hatched = extract(plan("hatched_plan.pdf"))
        with_hatch, _ = anim.storyboard(hatched, width=160, height=120)
        plain, _ = anim.storyboard(self.model, width=160, height=120)
        self.assertGreater(len(with_hatch), len(plain))

    def test_the_materials_beat_uses_real_rulings(self):
        from roomgraph.export.anim import _hatch_rulings

        hatched = extract(plan("hatched_plan.pdf"))
        rulings = _hatch_rulings(hatched)
        self.assertEqual(len(rulings), 2)
        materials = sorted(name for name, _ in rulings)
        self.assertEqual(materials, ["BE TONG", "GACH XAY"])
        for _name, group in rulings:
            self.assertGreater(len(group), 20)

    def test_write_produces_a_playable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plan.gif")
            n = anim.write(self.model, path, width=160, height=120)
            self.assertGreater(n, 20)
            self.assertGreater(os.path.getsize(path), 200)


def _decode_gif(data: bytes) -> tuple[list[tuple[int, int, int]], list[list[int]]]:
    """A deliberately independent GIF reader, used only to verify the writer."""
    pos = 6
    w = int.from_bytes(data[pos : pos + 2], "little")
    h = int.from_bytes(data[pos + 2 : pos + 4], "little")
    flags = data[pos + 4]
    pos += 7
    table_size = 1 << ((flags & 0x07) + 1)
    palette = [
        (data[pos + i * 3], data[pos + i * 3 + 1], data[pos + i * 3 + 2])
        for i in range(table_size)
    ]
    pos += table_size * 3

    frames: list[list[int]] = []
    while pos < len(data):
        block = data[pos]
        if block == 0x3B:
            break
        if block == 0x21:  # extension
            pos += 2
            while data[pos]:
                pos += data[pos] + 1
            pos += 1
            continue
        if block != 0x2C:
            pos += 1
            continue
        pos += 10
        if data[pos - 1] & 0x80:
            raise AssertionError("local colour tables not expected")
        min_code_size = data[pos]
        pos += 1
        chunks = bytearray()
        while data[pos]:
            n = data[pos]
            chunks += data[pos + 1 : pos + 1 + n]
            pos += n + 1
        pos += 1
        frames.append(_lzw_decode(bytes(chunks), min_code_size, w * h))
    return palette, frames


def _lzw_decode(data: bytes, min_code_size: int, expected: int) -> list[int]:
    clear, end = 1 << min_code_size, (1 << min_code_size) + 1
    table: list[list[int]] = [[i] for i in range(clear)] + [[], []]
    width = min_code_size + 1
    out: list[int] = []
    prev: list[int] | None = None
    acc = nbits = 0
    for byte in data:
        acc |= byte << nbits
        nbits += 8
        while nbits >= width:
            code = acc & ((1 << width) - 1)
            acc >>= width
            nbits -= width
            if code == clear:
                table = [[i] for i in range(clear)] + [[], []]
                width = min_code_size + 1
                prev = None
                continue
            if code == end:
                return out[:expected]
            if code < len(table):
                entry = table[code]
            elif prev is not None:
                entry = prev + prev[:1]
            else:
                raise AssertionError("corrupt stream")
            out.extend(entry)
            if prev is not None:
                table.append(prev + entry[:1])
                if len(table) >= (1 << width) and width < 12:
                    width += 1
            prev = entry
    return out[:expected]


if __name__ == "__main__":
    unittest.main()
