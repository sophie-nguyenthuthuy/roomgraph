"""roomgraph -- vector floor plan PDF to rooms, openings and a room graph.

    from roomgraph import extract
    model = extract("plan.pdf", scale="1:50")
    for room in model.rooms:
        print(room.name, room.area_gross_m2, model.graph.neighbours(room.id))

Stdlib only, on purpose: the PDF reader, the geometry, the IFC writer and the
GIF encoder are all in this package.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "extract", "PlanModel", "Room", "Wall", "Opening", "RoomGraph"]


def __getattr__(name: str):
    # Imported lazily so `roomgraph --version` and `roomgraph symbols` stay fast.
    if name in ("extract", "PlanModel"):
        from . import model as _model

        return getattr(_model, name)
    if name in ("Wall", "Opening"):
        from . import walls as _walls

        return getattr(_walls, name)
    if name == "Room":
        from . import rooms as _rooms

        return _rooms.Room
    if name == "RoomGraph":
        from . import adjacency as _adj

        return _adj.RoomGraph
    raise AttributeError(name)
