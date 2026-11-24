"""The three-agent demo is also an end-to-end test of the protocol."""

import importlib.util
import json
from pathlib import Path

DEMO = Path(__file__).resolve().parents[2] / "examples" / "three_agents.py"


def load_demo():
    spec = importlib.util.spec_from_file_location("three_agents", DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_runs_and_never_leaks_the_busy_reason(capsys):
    log = load_demo().main(auto_yes=True)
    intents = [m["intent"] for m in log["brand_saw"]]
    assert intents == ["answer", "accept"]
    everything_brand_saw = json.dumps(log["brand_saw"], ensure_ascii=False)
    assert "tedarikçi" not in everything_brand_saw.lower()
    assert "supplier@example.com" not in everything_brand_saw
    assert log["accept"]["body"]["slot"] == "2026-11-27T11:00"
    assert log["supplier_slot"] == "2026-12-02 15:00"
