"""Run the language-neutral conformance vectors from spec/vectors."""

import json
from pathlib import Path

import pytest

from elci import DisclosurePolicy

VECTORS = Path(__file__).resolve().parents[2] / "spec" / "vectors"
CASES = json.loads((VECTORS / "disclosure.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_disclosure_vector(case):
    policy = DisclosurePolicy(allowed=case["policy"])
    assert policy.redact(case["input"]) == case["expected"]
