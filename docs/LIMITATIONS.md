# What this does not do

Read this before trusting a number.

## Scanned drawings are out of scope

roomgraph reads **vector** geometry from the PDF content stream. A scan is a
raster image in a PDF wrapper: there are no lines to read, and `extract` will
report zero walls and say so.

This is a deliberate boundary, not a gap waiting to be filled. Line and symbol
detection on scans is a research problem -- deskewing, binarisation, vectorising,
handling hatch and noise, then everything below on top of an uncertain result.
Clean CAD exports are a weekend. Mixing the two in one tool means the honest
outputs inherit the confidence of the guessed ones.

If your input is scanned, vectorise it first with something built for that, then
bring the result here.

## Scale is inferred, and everything depends on it

A CAD export carries no units. We recover millimetres-per-point from dimension
strings, a title-block ratio, or door widths, in that order, and every result
states which source it used and how confident it is.

Get it wrong and every area is wrong by the **square** of the error. A 1.5x
scale error makes a 20 m² room read as 45 m².

Mitigations, all of them partial:

* pass `--scale 1:50` when you know it; that path is exact
* the printed room areas on the drawing are cross-checked against the computed
  ones, and a disagreement over 3% becomes a warning
* a scale bar, where one is drawn, is measured against its own label and a
  disagreement becomes a warning -- an independent witness, since the scale
  itself came from dimension strings
* a stated travel distance is compared against the measured escape route
* implausible wall thicknesses cause extraction to fail loudly rather than
  produce a plausible-looking wrong answer

## Walls must be drawn as paired faces

The extractor looks for two parallel lines 60-420 mm apart. That covers almost
all architectural output. It does not cover:

* **single-line walls** (schematic or early-design drawings) -- nothing pairs,
  so no rooms
* **poché / solid-filled walls** where the fill is a single closed path with no
  inner and outer line
* **very thick walls** (over 420 mm): basement retaining, some party walls
* **curved walls** -- a curve is clustered as many short lines with different
  angles and will not pair into one wall

## Openings

An opening is found where both wall faces stop. Two consequences:

* a door drawn **over** a continuous wall, with no break in the faces, is not
  found as an opening at all
* a drafting gap left by accident is reported as an opening

Symbols then classify the gaps that were found. The library covers swing,
double, sliding, folding, revolving and roller doors; flat, bay and corner
windows; curtain walling; cased openings; and at room scope straight and spiral
stairs, sanitary fittings and lift cars. Kitchen fittings, escalators, ramps and
structural columns are not covered -- see [SYMBOLS.md](SYMBOLS.md), that is the
contributor unit.

A revolving door is found from its radiating leaves, so a drum drawn as a
polygon rather than an arc still matches (the arc only raises confidence) but a
drum drawn with no leaves at all does not.

A roller shutter needs either a corrugated curtain or a visible barrel. Drawn as
a bare line it is indistinguishable from a sliding leaf and is reported as one.

Curtain walling is found from the rhythm of its mullions, not the glazing, so a
long glazed run with no mullions drawn is reported as an ordinary window. Runs
this wide only reach a detector because `walls.MAX_OPENING` allows gaps up to
8 m; a gap that wide with nothing drawn in it matches no symbol and warns.

Sanitary fittings are a size catalogue, so anything coincidentally
bath-shaped in a small room will be claimed, and the ranges for basins, bidets
and WCs genuinely overlap in reality as well as here. Fittings are only looked
for in rooms under 30 m2, and never in a room named as a kitchen.

Several room symbols are separated by facts other than shape, because in plan
they are the same rectangle:

* **kitchen units and columns** are both 600 mm squares. Columns must stand
  clear of their neighbours; kitchen units must abut in a run containing at
  least one element longer than 900 mm. A drawing that violates either
  convention will be read the other way.
* **a ramp** is identified by its gradient label, not its geometry. An
  unlabelled band is a corridor as far as this is concerned, and no slope
  enters the model.
* **a fire shutter** is a roller shutter on a fire-rated CAD layer. Strip the
  layers and it is reported as an ordinary roller shutter, which is the honest
  answer -- the drawing no longer says.
* **an escalator** is a stair flight plus balustrades running its full length.
  `stairs` stands down when it sees them, so the two never both report.
* **a turning circle** must be empty. That is what the mark asserts, and it is
  also what separates it from a spiral stair's enclosing circle.
* **a travelator and an escalator** are the same drawing. The one is claimed
  when the drawing names it or when the run is longer than any single escalator
  flight (16 m); otherwise the other keeps it.
* **a dumbwaiter and a lift** are the same crossed box at different sizes, and
  the two ranges are kept apart so neither can claim the other's.
* **a desk** is only claimed in a room that suits one, or beside a bed. A
  1700 by 750 rectangle alone in an unnamed room could as easily be a bath, so
  nothing is said.
* **planting** is identified by a ragged outline. A tree drawn as a plain
  circle is not distinguished from a turning circle, and neither is claimed.
* **fire equipment** is layer-driven, like the fire shutter. Strip the layers
  and it finds nothing.
* **industrial plant** has no shape at all -- an AHU is whatever the
  manufacturer made it. It is found by services layer, equipment label, or the
  room being a plant room, and by nothing else. It is the most
  drawing-dependent symbol here.
* **lab benching and kitchen units** are separated by depth alone: 600 for a
  kitchen, 750-900 for a bench, 1500-1800 for an island. The ranges do not
  overlap, so a drawing using unusual depths will be read as the other, or as
  neither.
* **a ward and its furniture** both report. Unlike the stair-and-escalator
  case, where one name for one object was wrong, the ward is the room and the
  beds are its contents: two separate true statements.
* **theatre seating** needs a dozen seats in at least two rows. A single row of
  chairs, or a meeting table's worth, is left alone.
* **a structural grid** is found from lines that *end at a bubble*. An external
  wall is just as long as a gridline, so length alone would let the walls into
  the sample and destroy the bay spacing. A grid drawn without reference
  bubbles is not detected.
* **an escape route** must be an open polyline on an escape layer. Its measured
  length is compared against any stated travel distance, the same cross-check
  the room areas get -- but strip the layers and it finds nothing.
* **a loading dock** is label-driven. A leveller plate is a 2 by 2 metre
  rectangle, which is a rug, a plinth or a hatch until the drawing says
  otherwise.
* **a raised access floor** must have its tiles drawn. An annotation alone does
  not do it.
* **a section mark and a gridline** are both long lines ending in lettered
  bubbles. A section's two bubbles carry the *same* letter, where a grid runs
  A, B, C -- that pairing is the only thing separating them, and a section
  drawn without matching letters will be counted as a gridline.
* **a revision cloud and planting** are the same ragged blob. The revision
  layer decides; without it the shape is left to `planting`, which is the
  better of the two wrong answers.
* **an elevation mark** is identified by what it is *not* attached to: no twin
  bubble carrying its letter, and no long line ending at it. A drawing that
  omits the arrow is not detected.
* **a door schedule** is read from its title and its references, not from the
  table rules. Its count is compared against the doors found and a mismatch
  warns -- which cuts both ways, since a schedule can be out of date.
* **a hatch legend** must be a column beneath its title. Anything swatch-sized
  elsewhere on the sheet -- an arrowhead, for one -- would otherwise join it.
  The hatch patterns themselves are not identified; only the key that names
  them.
* **a dimension chain** matches each value to the segment it sits beside, by
  proximity and not by length. Pairing on length would make the sum check
  tautological, so it deliberately allows the arithmetic to disagree -- at the
  cost of occasionally pairing a stray label with the wrong line.
* **spot levels** are read purely from text. They are also the only height
  information in the model -- everything else here is two dimensional, because
  a plan is.

## Arcs are fitted to sampled curves

`ctx.arcs()` fits circles to polylines, which has a trap worth knowing: the
four corners of *any* rectangle lie exactly on a circle. A fit that only checks
residual therefore calls every box in the drawing a perfect arc.

Arcs are consequently required to be finely sampled -- at least eight points,
with no step longer than 0.6 of the fitted radius. A curve flattened out of a
bezier passes easily; a polygon does not. If an exporter emits arcs as coarse
polylines, they will be missed rather than mistaken.

A folding door is identified from three or more *equal* leaves alternating
across the wall line. A two-leaf bi-fold drawn as a plain V is deliberately not
claimed: at two facets nothing distinguishes it from a triangular bay window,
and it falls back to whichever of those fits rather than being guessed at.

A bay is found from the facet chain that projects through the opening, so a bay
drawn only as glazing lines with no projecting outline reads as a flat window.
Its projection is also excluded from room area, which is correct for a gross
internal figure and wrong if you wanted the bay counted.

## Reconstructed corners

A corner window removes the corner: both walls stop short of it, there is no
face gap to find, and the room does not enclose at all. `walls.bridge_corners`
rejoins free wall ends that point at a shared missing corner and records the
length it invented as a *bridged* opening.

That is geometry we made up, so it is deliberately narrow:

* both ends must be genuinely free -- not meeting another wall's end, not
  landing on another wall's run
* the corner angle must be 55-125 degrees
* neither wall may gain more than 3000 mm
* each end is used at most once, closest pair first

Consequences worth knowing: a corner window arrives as **two** openings, one per
wall, because each wall really does have one. Only the corner-removed variant is
detected -- a corner window drawn with a mullion, where the walls do meet, reads
as two ordinary flat windows. And a wall that simply stops in mid-air near
another one will be joined up, which is right for a corner window and wrong for
a drawing that meant to leave a gap.

## Geometry

* **Areas are 2D.** Sloped ceilings, voids, split levels and mezzanines are all
  invisible on a plan and are ignored.
* **`area_net_m2` is approximate.** It offsets each room edge inward by half the
  thickness of its wall and re-intersects. That is correct for the convex-ish,
  mostly rectilinear rooms plans are made of. It does not do a straight skeleton,
  so a sharply reflex corner can produce a bad offset; when the result is
  implausible we fall back to the gross area rather than report a wrong number.
* **Multi-storey is not handled.** One page is one storey. There is no stair
  matching between levels, and the IFC has a single `IfcBuildingStorey`.
* **Room polygons are the wall centreline arrangement**, so two rooms sharing a
  wall share that centreline exactly. Areas therefore sum to the centreline
  envelope, not to a surveyed floor area.

## PDF support

Implemented: object and cross-reference scanning, object streams, Flate,
ASCIIHex, ASCII85, RunLength, PNG predictors, form XObjects, optional content
(layers), Type1/TrueType/Type0 text via ToUnicode.

Not implemented:

* **encrypted PDFs** -- even empty-password ones will fail to decode
* **raster image content** (DCTDecode and friends) -- skipped, see above
* **shading and pattern fills** -- ignored, which is usually right for plans
* **clipping paths** -- parsed but not applied, so geometry clipped away in a
  viewer is still extracted

## IFC

Rough on purpose; [the exporter's docstring](../roomgraph/export/ifc.py) says
what that means. In short: real spatial hierarchy and real plan geometry, but
every height is an assumption, geometry is in world coordinates rather than a
local placement tree, and there is no material, no type object, and no property
set beyond base quantities. It is a massing model to correct in a BIM tool, not
a survey.

## The fixtures are synthetic

`examples/make_fixtures.py` writes the test PDFs. They imitate how real
exporters emit plans -- paired faces, optional-content layers, bezier arcs,
dimension strings -- and having known ground truth is what makes the end-to-end
assertions meaningful.

But they were written by the same person as the parser, which is exactly the
bias you should worry about. Passing tests demonstrate the pipeline is
self-consistent. They do not demonstrate that AutoCAD, Revit, ArchiCAD or
Vectorworks emit what these fixtures assume. Real files from real exporters are
the most valuable contribution this project could receive.
