"""Load the JSON Schemas bundled with the package.

``elci/schemas/`` is a copy of ``spec/schemas/``; ``tests/test_packaging.py`` keeps them identical.
"""

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_DIR = Path(__file__).parent / "schemas"


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
