"""Packaging invariants: what ships on PyPI must match the spec and the declared version."""

import re
from pathlib import Path

import elci
from elci import _schemas

ROOT = Path(__file__).resolve().parents[2]


def test_bundled_schemas_match_the_spec():
    spec = sorted((ROOT / "spec" / "schemas").glob("*.json"))
    assert spec, "spec/schemas is empty"
    bundled = {p.name: p.read_bytes() for p in _schemas.SCHEMA_DIR.glob("*.json")}
    assert set(bundled) == {p.name for p in spec}
    for path in spec:
        assert bundled[path.name] == path.read_bytes(), f"copy spec/schemas/{path.name} to python/src/elci/schemas/"


def test_version_matches_pyproject():
    text = (ROOT / "python" / "pyproject.toml").read_text(encoding="utf-8")
    assert elci.__version__ == re.search(r'^version = "([^"]+)"', text, re.M).group(1)
