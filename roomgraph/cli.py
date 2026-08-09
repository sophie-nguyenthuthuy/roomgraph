"""Command line interface.

    roomgraph extract plan.pdf -o out/
    roomgraph inspect plan.pdf          # what the PDF actually contains
    roomgraph symbols                   # what the library can recognise
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .model import extract
from .scale import from_dimension_text, from_door_width, from_titleblock

FORMATS = ("json", "geojson", "ifc", "svg", "gif")


def _fmt_table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    for r in rows:
        out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)


def cmd_extract(args: argparse.Namespace) -> int:
    from .export import anim, geojson, ifc, json_model, svg

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        print(f"unknown format(s): {', '.join(bad)}; choose from {', '.join(FORMATS)}", file=sys.stderr)
        return 2

    try:
        model = extract(
            args.plan,
            page=args.page,
            scale=args.scale,
            min_room_area_m2=args.min_room_area,
        )
    except FileNotFoundError:
        print(f"no such file: {args.plan}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"could not read {args.plan}: {exc}", file=sys.stderr)
        return 1

    outdir = args.out or os.path.dirname(os.path.abspath(args.plan))
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.plan))[0]

    geo_origin = None
    if args.geo_origin:
        try:
            lat, lon = (float(v) for v in args.geo_origin.split(","))
            geo_origin = (lat, lon)
        except ValueError:
            print("--geo-origin must be 'lat,lon'", file=sys.stderr)
            return 2

    written: list[str] = []
    for fmt in formats:
        path = os.path.join(outdir, f"{stem}.{'geojson' if fmt == 'geojson' else fmt}")
        if fmt == "json":
            json_model.write(model, path)
        elif fmt == "geojson":
            geojson.write(model, path, geo_origin=geo_origin)
        elif fmt == "ifc":
            ifc.write(model, path)
        elif fmt == "svg":
            svg.write(model, path)
        elif fmt == "gif":
            anim.write(model, path)
        written.append(path)

    if not args.quiet:
        _report(model, written)
    return 1 if (args.strict and model.warnings) else 0


def _report(model, written: list[str]) -> None:
    sc = model.scale.to_dict()
    print(f"{model.source}  page {model.page}")
    print(f"  scale     {sc['drawing_scale']}  ({sc['source']}, confidence {sc['confidence']}) - {sc['detail']}")
    print(f"  walls     {len(model.walls)}")
    print(f"  openings  {len(model.openings)}  {model.counts()}")
    print()

    rows = []
    for r in model.rooms:
        rows.append(
            [
                r.id,
                (r.name or "-")[:22],
                r.category,
                f"{r.area_gross_m2:.2f}",
                f"{r.area_net_m2:.2f}",
                f"{r.labelled_area_m2:.2f}" if r.labelled_area_m2 else "-",
                r.area_check(),
                ",".join(model.graph.neighbours(r.id)) or "-",
            ]
        )
    if rows:
        print(
            _fmt_table(
                rows,
                ["id", "name", "category", "gross m2", "net m2", "labelled", "check", "connects to"],
            )
        )
        print()

    if model.openings:
        rows = [
            [
                model.opening_id(op),
                op.kind,
                op.symbol or "-",
                f"{op.width:.0f}",
                f"{op.confidence:.2f}",
            ]
            for op in model.openings
        ]
        print(_fmt_table(rows, ["id", "kind", "symbol", "width mm", "conf"]))
        print()

    if model.features:
        for f in model.features:
            print(f"  feature: {f.room} {f.kind} ({f.symbol}, {f.confidence:.2f}) {f.meta}")
        print()

    for w in model.warnings:
        print(f"  warning: {w}")
    if model.warnings:
        print()

    for path in written:
        print(f"  wrote {path}")


def cmd_inspect(args: argparse.Namespace) -> int:
    from .pdf.content import read_pdf
    from .pdf.document import Document

    try:
        doc = Document.from_path(args.plan)
    except FileNotFoundError:
        print(f"no such file: {args.plan}", file=sys.stderr)
        return 2
    pages = doc.pages()
    print(f"{os.path.basename(args.plan)}: {len(pages)} page(s)")
    if not pages:
        return 1

    geo = read_pdf(args.plan, page_index=args.page)
    print(f"  media box   {tuple(round(v, 1) for v in geo.media_box)} pt")
    print(f"  primitives  {len(geo.primitives)}")
    print(f"  text runs   {len(geo.texts)}")
    layers = geo.layers()
    if layers:
        print("  layers:")
        for name, n in sorted(layers.items(), key=lambda kv: -kv[1]):
            print(f"    {n:6d}  {name or '(none)'}")

    print("\n  scale candidates:")
    for fn in (from_dimension_text, from_titleblock, from_door_width):
        res = fn(geo)
        label = fn.__name__.replace("from_", "")
        if res:
            d = res.to_dict()
            print(f"    {label:15s} {d['drawing_scale']:>7s}  conf {d['confidence']:.2f}  {d['detail']}")
        else:
            print(f"    {label:15s} {'-':>7s}")

    if args.text:
        print("\n  text:")
        for t in geo.texts[: args.text]:
            print(f"    ({t.origin.x:7.1f},{t.origin.y:7.1f}) h={t.height:5.2f}  {t.text!r}")
    return 0


def cmd_symbols(args: argparse.Namespace) -> int:
    from .symbols import fixtures, registry

    reg = registry()
    fx = fixtures()
    rows = [
        [
            s.id,
            s.scope,
            s.kind,
            str(len(fx.get(s.id, []))),
            s.description or s.name,
        ]
        for s in sorted(reg.values(), key=lambda s: (s.scope, s.id))
    ]
    print(_fmt_table(rows, ["id", "scope", "kind", "fixtures", "detects"]))
    print(f"\n{len(reg)} symbols. Add one: see docs/SYMBOLS.md")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="roomgraph",
        description="Turn a vector floor plan PDF into rooms, openings and a room graph.",
    )
    p.add_argument("--version", action="version", version=f"roomgraph {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("extract", help="extract a structured model and write exports")
    e.add_argument("plan", help="path to a vector PDF")
    e.add_argument("-o", "--out", help="output directory (default: alongside the input)")
    e.add_argument("-p", "--page", type=int, default=0, help="page index, 0-based")
    e.add_argument(
        "-s",
        "--scale",
        help="drawing scale, e.g. '1:50', or millimetres per point, e.g. '17.64mm'",
    )
    e.add_argument(
        "-f",
        "--formats",
        default="json,geojson,ifc,svg",
        help=f"comma separated, from: {','.join(FORMATS)}",
    )
    e.add_argument("--geo-origin", help="'lat,lon' to write GeoJSON in WGS84 instead of local metres")
    e.add_argument("--min-room-area", type=float, default=0.7, help="drop faces below this, m2")
    e.add_argument("--strict", action="store_true", help="exit non-zero if there are warnings")
    e.add_argument("-q", "--quiet", action="store_true")
    e.set_defaults(func=cmd_extract)

    i = sub.add_parser("inspect", help="show what the PDF contains, before extraction")
    i.add_argument("plan")
    i.add_argument("-p", "--page", type=int, default=0)
    i.add_argument("--text", type=int, default=0, metavar="N", help="print the first N text runs")
    i.set_defaults(func=cmd_inspect)

    s = sub.add_parser("symbols", help="list the symbol library")
    s.set_defaults(func=cmd_symbols)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
