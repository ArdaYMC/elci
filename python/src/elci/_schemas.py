"""Locate the JSON Schemas shipped with the spec."""

import json
from functools import lru_cache
from pathlib import Path

_CANDIDATES = (
    Path(__file__).parent / "schemas",  # installed wheel
    Path(__file__).resolve().parents[3] / "spec" / "schemas",  # source checkout
)


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    for base in _CANDIDATES:
        path = base / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"schema {name!r} not found in {_CANDIDATES}")
