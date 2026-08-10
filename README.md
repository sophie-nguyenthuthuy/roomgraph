# roomgraph

**A vector floor plan PDF goes in. Rooms, areas, doors, windows and a room
adjacency graph come out.** JSON, GeoJSON and a rough IFC.

![a floor plan dissolving into a coloured room graph](docs/media/apartment.gif)

No dependencies. The PDF reader, the geometry, the IFC writer and the GIF
encoder above are all in this package, in the standard library.

```bash
python -m roomgraph.cli extract plan.pdf -o out/
```

```
plan.pdf  page 0
  scale     1:50  (dimension, confidence 0.85) - 2 dimension string(s) agreed
  walls     6
  openings  5  {'door': 3, 'window': 2}

id    name         category  gross m2  net m2  labelled  check  connects to
----  -----------  --------  --------  ------  --------  -----  -----------
R001  PHONG KHACH  living    34.56     32.35   34.60     ok     R002,R003
R002  BEP          kitchen   17.28     15.92   17.30     ok     R001
R003  PHONG NGU    bedroom   17.28     15.92   17.30     ok     R001

id    kind    symbol      width mm  conf
----  ------  ----------  --------  ----
O001  door    door_swing  1000      0.98
O002  window  window      1200      0.90
O003  window  window      1500      0.90
O004  door    door_swing  800       0.98
O005  door    door_swing  900       0.98
```

That `check` column is the drawing's own printed room area compared against the
measured one. It is the cheapest available proof that the scale was read right.

## Scope

**Clean CAD-exported PDFs.** Scans are explicitly out of scope, and that is the
whole reason this is finishable: line and symbol detection on a scan is a
research project, while a vector export already contains the lines — they just
need to be understood. Feed it a scan and it will tell you it found no walls
rather than guess.

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for the rest of the boundary,
including the ones that will bite you.

## How it works

```
PDF content stream    walls are drawn as TWO parallel lines, and an
       |              opening is where BOTH of them stop. Everything
       v              downstream follows from that one observation.
  scale calibration   dimension strings > title block > door widths,
       |              each reported with its confidence
       v
  line clustering     segments -> the infinite lines they lie on
       |
       v
  face pairing        parallel lines 60-420mm apart -> walls + openings
       |
       v
  corner repair       free ends aimed at a missing corner are rejoined,
       |              the invented length becoming a bridged opening
       v
  planar arrangement  split at crossings and T-junctions, walk half-edges
       |              -> minimal cycles = rooms
       v
  symbol library      each gap classified: door, window, cased opening
       |
       v
  room graph          shared wall = adjacent; opening on it = walkable
```

Pairing lines before pairing segments is the part that matters. Match raw
segments first and every wall broken by a doorway falls apart — and every real
plan has those.

## Install

```bash
git clone https://github.com/sophie-nguyenthuthuy/roomgraph
cd roomgraph
python -m roomgraph.cli --help
```

Python 3.10+. That is the entire installation.

## Use

```bash
# everything, into out/
python -m roomgraph.cli extract plan.pdf -o out/ -f json,geojson,ifc,svg,gif

# when you know the scale, say so -- it is exact, and detection is not
python -m roomgraph.cli extract plan.pdf --scale 1:100

# what does this PDF actually contain? layers, text, scale candidates
python -m roomgraph.cli inspect plan.pdf --text 20

# what can the library recognise?
python -m roomgraph.cli symbols

# fail the build if anything is uncertain
python -m roomgraph.cli extract plan.pdf --strict
```

As a library:

```python
from roomgraph import extract

model = extract("plan.pdf", scale="1:50")

for room in model.rooms:
    print(room.name, room.area_gross_m2, model.graph.neighbours(room.id))

print(model.graph.is_connected())     # is every room reachable?
print([e.a for e in model.graph.entrances])
for w in model.warnings:
    print("warning:", w)
```

## Outputs

| Format | What it is for |
|---|---|
| **JSON** | the canonical model — rooms, walls, openings, graph, warnings. Every other export is a projection of this. |
| **GeoJSON** | rooms as polygons, walls as lines, openings as segments. Local metres by default, or pass `--geo-origin lat,lon` for real WGS84. |
| **IFC** | IFC4 SPF: Project/Site/Building/Storey, `IfcSpace` per room, `IfcWallStandardCase` with real voids, `IfcDoor`/`IfcWindow` filling them. Rough — every height is an assumption. |
| **SVG** | the figure above, with a toggleable graph layer. Doubles as the debugging view when a room comes out wrong. |
| **GIF** | the animation at the top. Written by [`export/raster.py`](roomgraph/export/raster.py), LZW and all. |

## The symbol library is the contributor unit

**One symbol is one file** in `roomgraph/symbols/`. You add a file with a
`SYMBOL` and its `FIXTURES`; you do not touch the pipeline, the exporters, or
the tests. The suite discovers your symbol, runs your fixtures, and separately
checks that your detector does not outbid an existing symbol on that symbol's
own fixtures — so a too-greedy detector fails loudly instead of quietly stealing
openings.

Currently:

| id | scope | detects |
|---|---|---|
| `door_swing` | opening | leaf line plus a swing arc of the opening's width |
| `door_double` | opening | two half-width arcs hinged on opposite jambs |
| `door_sliding` | opening | one leaf parallel to the wall, offset, no arc |
| `door_folding` | opening | three or more equal leaves zigzagging across the opening |
| `door_revolving` | opening | evenly spaced leaves radiating from a hub at the opening centre |
| `door_roller` | opening | a slatted curtain, corrugated or wound onto a barrel |
| `door_fire_shutter` | opening | the same shutter, drawn on a fire-rated layer |
| `window` | opening | two or more glazing lines spanning the opening |
| `window_bay` | opening | straight facets projecting out of the wall, jamb to jamb (box, canted, bow) |
| `window_corner` | opening | glazing wrapping a corner the drawing left out |
| `curtain_wall` | opening | a wide glazed run divided by mullions at a regular module |
| `opening_plain` | opening | a gap with nothing drawn in it |
| `stairs` | room | three or more evenly spaced parallel treads |
| `stairs_spiral` | room | six or more treads radiating from a newel |
| `escalator` | room | a long run of steps between full-length balustrades |
| `travelator` | room | a walkway band, named or longer than any escalator |
| `ramp` | room | a band carrying a gradient label |
| `turning_circle` | room | an empty 1500 mm circle of clear floor |
| `kitchen` | room | units sharing one depth: a fitted run |
| `column` | room | small poched or repeating squares |
| `sanitary` | room | outlines matching standard bath, shower, WC, bidet or basin sizes |
| `lift` | room | a car-sized rectangle with both diagonals drawn |
| `dumbwaiter` | room | the same crossed box, too small to stand in |
| `parking_bay` | room | two or more car-sized rectangles of matching size |
| `furniture_layout` | room | standard bed and desk sizes |
| `fire_equipment` | room | cabinets on a fire layer or beside a fire label |
| `planting` | room | scalloped canopies: ragged where a circle is smooth |

Room-scope symbols are not mutually exclusive: every one reports independently,
so a bathroom can carry both fittings and a stair. Opening-scope symbols compete,
and the most confident wins.

Twenty-seven symbols so far. What is missing is less a list than a kind: this
library knows the things a plan draws the same way everywhere. It does not know
anything specialised -- laboratory benching, theatre seating, hospital bed bays,
industrial plant -- and each of those is a file.

Not every symbol is only a symbol file, though. A corner window deletes the
corner, so both walls stop short, nothing encloses, and the room is lost before
any detector runs — that one needed `walls.bridge_corners` to reconstruct the
missing corner first. If a symbol changes what counts as a *wall*, expect to
touch the wall stage too.

**[docs/SYMBOLS.md](docs/SYMBOLS.md)** has the local-frame diagram, the
context API, the confidence bands and a checklist.

## Development

```bash
python examples/make_fixtures.py            # generate the fixture PDFs
python -m unittest discover -s tests        # 205 tests
make test                                   # the same, plus a demo render
```

Fixture PDFs are generated by `examples/make_fixtures.py` rather than committed,
so their ground truth is written down next to the geometry that produces it. They
are synthetic — see the last section of
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) for why that matters and what would
help most.

## Licence

MIT.
