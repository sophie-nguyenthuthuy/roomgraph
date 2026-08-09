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

Symbols then classify the gaps that were found. The library covers single swing,
double swing, sliding, flat window, bay window and cased opening, plus stairs at
room scope. Corner windows, folding and revolving doors, curtain walling and
roller shutters are not covered -- see [SYMBOLS.md](SYMBOLS.md), that is the
contributor unit.

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
