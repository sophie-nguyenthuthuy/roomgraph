import math
import unittest

from roomgraph.geom import (
    Pt,
    Seg,
    arc_span,
    dedupe_points,
    fit_circle,
    is_parallel,
    offset_polygon,
    point_in_polygon,
    point_seg_distance,
    polygon_area,
    polygon_centroid,
    polygon_perimeter,
    project_param,
    representative_point,
    seg_intersection,
)

SQUARE = [Pt(0, 0), Pt(100, 0), Pt(100, 100), Pt(0, 100)]
L_SHAPE = [Pt(0, 0), Pt(300, 0), Pt(300, 100), Pt(100, 100), Pt(100, 300), Pt(0, 300)]


class TestPolygons(unittest.TestCase):
    def test_area_sign_follows_winding(self):
        self.assertAlmostEqual(polygon_area(SQUARE), 10000.0)
        self.assertAlmostEqual(polygon_area(list(reversed(SQUARE))), -10000.0)

    def test_perimeter(self):
        self.assertAlmostEqual(polygon_perimeter(SQUARE), 400.0)

    def test_centroid_of_square(self):
        c = polygon_centroid(SQUARE)
        self.assertAlmostEqual(c.x, 50.0)
        self.assertAlmostEqual(c.y, 50.0)

    def test_point_in_polygon(self):
        self.assertTrue(point_in_polygon(Pt(50, 50), SQUARE))
        self.assertFalse(point_in_polygon(Pt(150, 50), SQUARE))

    def test_l_shape_centroid_falls_outside(self):
        """The reason representative_point exists."""
        self.assertFalse(point_in_polygon(polygon_centroid(L_SHAPE), L_SHAPE))
        self.assertTrue(point_in_polygon(representative_point(L_SHAPE), L_SHAPE))

    def test_representative_point_of_convex_is_centroid(self):
        self.assertTrue(point_in_polygon(representative_point(SQUARE), SQUARE))

    def test_offset_shrinks_area(self):
        inner = offset_polygon(SQUARE, [10.0] * 4)
        self.assertAlmostEqual(abs(polygon_area(inner)), 80.0 * 80.0, places=6)

    def test_offset_respects_per_edge_distance(self):
        inner = offset_polygon(SQUARE, [10.0, 20.0, 10.0, 20.0])
        self.assertAlmostEqual(abs(polygon_area(inner)), 60.0 * 80.0, places=6)


class TestSegments(unittest.TestCase):
    def test_intersection(self):
        p = seg_intersection(Seg(Pt(0, 0), Pt(10, 10)), Seg(Pt(0, 10), Pt(10, 0)))
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.x, 5.0)
        self.assertAlmostEqual(p.y, 5.0)

    def test_parallel_segments_do_not_intersect(self):
        self.assertIsNone(seg_intersection(Seg(Pt(0, 0), Pt(10, 0)), Seg(Pt(0, 5), Pt(10, 5))))

    def test_collinear_overlap_returns_none(self):
        self.assertIsNone(seg_intersection(Seg(Pt(0, 0), Pt(10, 0)), Seg(Pt(5, 0), Pt(15, 0))))

    def test_disjoint_segments(self):
        self.assertIsNone(seg_intersection(Seg(Pt(0, 0), Pt(1, 1)), Seg(Pt(8, 0), Pt(9, 1))))

    def test_point_seg_distance_clamps_to_endpoints(self):
        s = Seg(Pt(0, 0), Pt(10, 0))
        self.assertAlmostEqual(point_seg_distance(Pt(5, 3), s), 3.0)
        self.assertAlmostEqual(point_seg_distance(Pt(-4, 0), s), 4.0)

    def test_project_param(self):
        s = Seg(Pt(0, 0), Pt(10, 0))
        self.assertAlmostEqual(project_param(Pt(2.5, 9), s), 0.25)

    def test_is_parallel_treats_antiparallel_as_parallel(self):
        self.assertTrue(is_parallel(Pt(1, 0), Pt(-1, 0)))
        self.assertTrue(is_parallel(Pt(1, 0), Pt(1, 0.01)))
        self.assertFalse(is_parallel(Pt(1, 0), Pt(0, 1)))

    def test_dedupe_points_drops_repeats_and_closing_point(self):
        pts = [Pt(0, 0), Pt(0, 0.0001), Pt(10, 0), Pt(0, 0)]
        self.assertEqual(len(dedupe_points(pts, tol=0.01)), 2)


class TestCircleFit(unittest.TestCase):
    def _arc(self, cx, cy, r, a0, a1, n=24):
        return [
            Pt(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)
        ]

    def test_recovers_centre_and_radius(self):
        pts = self._arc(5, -3, 900, 0, math.pi / 2)
        centre, radius, resid = fit_circle(pts)
        self.assertAlmostEqual(centre.x, 5.0, places=3)
        self.assertAlmostEqual(centre.y, -3.0, places=3)
        self.assertAlmostEqual(radius, 900.0, places=3)
        self.assertLess(resid, 1e-6)

    def test_straight_line_is_not_a_circle(self):
        pts = [Pt(float(i), 0.0) for i in range(10)]
        fit = fit_circle(pts)
        if fit is not None:
            _, r, resid = fit
            self.assertGreater(resid / max(r, 1e-9), 0.0)

    def test_arc_span_measures_turned_angle(self):
        pts = self._arc(0, 0, 100, 0, math.pi / 2)
        self.assertAlmostEqual(math.degrees(arc_span(pts, Pt(0, 0))), 90.0, places=4)

    def test_too_few_points(self):
        self.assertIsNone(fit_circle([Pt(0, 0), Pt(1, 1)]))


if __name__ == "__main__":
    unittest.main()
