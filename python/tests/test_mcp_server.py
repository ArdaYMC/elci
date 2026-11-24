import asyncio

import pytest

from elci import mcp_server


def test_route_prefers_agent_then_email(pair):
    cards, creator, brand = pair
    assert mcp_server.route("creator.example", "collaboration", resolve=cards.__getitem__)["via"] == "agent"
    assert mcp_server.route("creator.example", "scheduling", resolve=cards.__getitem__)["via"] == "email"


def test_discover_lists_public_agents(pair):
    cards, *_ = pair
    out = mcp_server.discover("brand.example", resolve=cards.__getitem__)
    assert out["agents"][0]["topics"] == ["collaboration"]


def test_accept_without_receipt_is_refused_before_sending(pair):
    cards, creator, _ = pair
    out = mcp_server.send_message("creator.example", creator.id, "collaboration", "accept", {},
                                  resolve=cards.__getitem__)
    assert out["sent"] is False and "request_approval" in out["reason"]


def test_draft_email_and_read_reply():
    draft = mcp_server.draft_email("s@example.com", "scheduling", "Acme", options=["Mon 10:00", "Tue 15:00"])
    assert "2. Tue 15:00" in draft["body"]
    raw = f"From: s@example.com\nSubject: Re\n\n1 olur\n\nelci-thread: {draft['thread']}\n"
    out = mcp_server.read_email_reply(raw)
    assert out["choice"] == 1 and out["thread"] == draft["thread"] and out["needs_confirmation"]


def test_redact_availability():
    rows = [{"slot": "Thu 14:00", "busy": True, "title": "secret"}]
    assert mcp_server.redact_availability(rows) == [{"slot": "Thu 14:00", "busy": True}]


def test_server_exposes_tools():
    pytest.importorskip("mcp")
    tools = asyncio.run(mcp_server.build_server().list_tools())
    names = {t.name for t in tools}
    assert {"discover", "route", "send_message", "check_inbox", "read_message", "request_approval",
            "approval_status", "draft_email", "read_email_reply", "redact_availability"} <= names
    for tool in tools:
        assert "resolve" not in str(tool.input_schema) and "store" not in str(tool.input_schema), tool.name
