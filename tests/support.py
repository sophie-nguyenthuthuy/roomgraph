"""Shared test helpers: fixture paths, generated on demand."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANS = os.path.join(ROOT, "examples", "plans")
MAKER = os.path.join(ROOT, "examples", "make_fixtures.py")


def ensure_fixtures() -> str:
    """Fixture PDFs are generated, not committed as binaries."""
    apartment = os.path.join(PLANS, "apartment.pdf")
    if not os.path.exists(apartment):
        subprocess.run([sys.executable, MAKER, PLANS], check=True, capture_output=True)
    return PLANS


def plan(name: str) -> str:
    ensure_fixtures()
    return os.path.join(PLANS, name)


def ground_truth() -> list[dict]:
    import json

    ensure_fixtures()
    with open(os.path.join(PLANS, "ground_truth.json")) as fh:
        return json.load(fh)
