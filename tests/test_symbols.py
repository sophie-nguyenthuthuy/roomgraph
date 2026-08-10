"""The contributor gate.

This file never needs editing to add a symbol. It walks the registry, runs
every fixture each symbol ships, and additionally checks that a symbol's own
positive fixtures are won by that symbol -- so a new detector that is too
greedy fails here rather than silently stealing openings from an existing one.
"""

from __future__ import annotations

import unittest

from roomgraph.geom import Pt, Seg
from roomgraph.symbols import (
    Fixture,
    OpeningContext,
    RoomContext,
    Symbol,
    best_match,
    coverage_of,
    fixtures,
    registry,
    symbols_for,
)


class TestRegistry(unittest.TestCase):
    def test_registry_is_not_empty(self):
        self.assertGreaterEqual(len(registry()), 5)

    def test_every_symbol_ships_fixtures(self):
        for sid, syms in fixtures().items():
            with self.subTest(symbol=sid):
                self.assertTrue(syms, f"{sid} ships no FIXTURES")
                self.assertTrue(
                    any(f.expect for f in syms), f"{sid} has no positive fixture"
                )
                self.assertTrue(
                    any(not f.expect for f in syms), f"{sid} has no negative fixture"
                )

    def test_symbol_metadata_is_complete(self):
        for sid, sym in registry().items():
            with self.subTest(symbol=sid):
                self.assertEqual(sym.id, sid)
                self.assertTrue(sym.name)
                self.assertTrue(sym.kind)
                self.assertTrue(sym.description, "a symbol should say what it detects")
                self.assertIn(sym.scope, ("opening", "room"))

    def test_scopes_partition_the_registry(self):
        total = len(symbols_for("opening")) + len(symbols_for("room"))
        self.assertEqual(total, len(registry()))

    def test_bad_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            Symbol(id="x", name="x", kind="x", detect=lambda c: None, scope="nope")


class TestFixtureWalk(unittest.TestCase):
    def test_all_fixtures(self):
        reg = registry()
        for sid, cases in sorted(fixtures().items()):
            sym = reg[sid]
            for case in cases:
                with self.subTest(symbol=sid, fixture=case.name):
                    match = sym.detect(case.context())
                    if case.expect:
                        self.assertIsNotNone(match, f"{sid} missed: {case.name}")
                        self.assertGreaterEqual(
                            match.confidence,
                            case.min_confidence,
                            f"{sid} matched {case.name} too weakly",
                        )
                        self.assertEqual(match.kind, sym.kind)
                    else:
                        self.assertIsNone(match, f"{sid} false positive: {case.name}")

    def test_positive_fixtures_are_won_by_their_own_symbol(self):
        """Openings compete, so a symbol must win its own fixtures outright."""
        reg = registry()
        for sid, cases in sorted(fixtures().items()):
            sym = reg[sid]
            if sym.scope != "opening":
                continue
            for case in cases:
                if not case.expect:
                    continue
                with self.subTest(symbol=sid, fixture=case.name):
                    winner = best_match(case.context(), sym.scope)
                    self.assertIsNotNone(winner)
                    self.assertEqual(
                        winner[0].id,
                        sid,
                        f"{case.name!r} was claimed by {winner[0].id} instead of {sid}",
                    )

    def test_room_symbols_are_not_outranked_within_their_own_kind(self):
        """Room features accumulate, so two symbols may both fire on one room --
        a ward is the room and the beds are its contents, and both are true.

        What must not happen is two symbols claiming the same *kind* and the
        wrong one winning: a spiral stair outranked by the straight-flight
        symbol would be a real error, where a ward reported alongside its
        furniture is not.
        """
        reg = registry()
        for sid, cases in sorted(fixtures().items()):
            sym = reg[sid]
            if sym.scope != "room":
                continue
            rivals = [s for s in symbols_for("room") if s.kind == sym.kind and s.id != sid]
            for case in cases:
                if not case.expect:
                    continue
                with self.subTest(symbol=sid, fixture=case.name):
                    ctx = case.context()
                    mine = sym.detect(ctx)
                    self.assertIsNotNone(mine)
                    for rival in rivals:
                        theirs = rival.detect(ctx)
                        if theirs is None:
                            continue
                        self.assertGreaterEqual(
                            mine.confidence,
                            theirs.confidence,
                            f"{case.name!r} was outranked by {rival.id}, which claims "
                            f"the same kind {sym.kind!r}",
                        )

    def test_detectors_survive_degenerate_input(self):
        empty_opening = OpeningContext(width=0.0, wall_thickness=0.0, strokes=[])
        empty_room = RoomContext(polygon=[], strokes=[])
        for sym in registry().values():
            with self.subTest(symbol=sym.id):
                ctx = empty_opening if sym.scope == "opening" else empty_room
                sym.detect(ctx)  # must not raise


class TestHelpers(unittest.TestCase):
    def test_coverage_of_full_span(self):
        segs = [Seg(Pt(-450, 0), Pt(450, 0))]
        self.assertAlmostEqual(coverage_of(segs, -450, 450), 1.0)

    def test_coverage_of_partial_span(self):
        segs = [Seg(Pt(-450, 0), Pt(0, 0))]
        self.assertAlmostEqual(coverage_of(segs, -450, 450), 0.5)

    def test_coverage_merges_overlaps(self):
        segs = [Seg(Pt(-450, 0), Pt(100, 0)), Seg(Pt(0, 0), Pt(450, 0))]
        self.assertAlmostEqual(coverage_of(segs, -450, 450), 1.0)

    def test_coverage_of_empty(self):
        self.assertEqual(coverage_of([], 0, 10), 0.0)

    def test_context_jambs_follow_width(self):
        ctx = OpeningContext(width=900, wall_thickness=110)
        left, right = ctx.jambs
        self.assertAlmostEqual(left.x, -450)
        self.assertAlmostEqual(right.x, 450)

    def test_broken_symbol_does_not_sink_the_run(self):
        """best_match must tolerate a contributed detector that throws."""

        def explode(ctx):
            raise RuntimeError("boom")

        import roomgraph.symbols as mod

        broken = Symbol(id="broken", name="Broken", kind="door", detect=explode)
        mod._REGISTRY["broken"] = broken
        try:
            ctx = Fixture(name="t", width=900, strokes=[], expect=True).context()
            best_match(ctx, "opening")  # must not raise
        finally:
            mod._REGISTRY.pop("broken", None)


if __name__ == "__main__":
    unittest.main()
