import pytest

from elci import AgentCard, CardError, well_known_url

CARD = {
    "elci": "0.0.1",
    "principal": {"name": "Test Person", "fallback": "mailto:test@example.com"},
    "agents": [
        {
            "id": "https://example.com/agents/creator",
            "name": "creator",
            "topics": ["collaboration"],
            "endpoint": "https://example.com/elci/creator",
            "keys": [{"kty": "OKP", "crv": "Ed25519", "x": "AAAA"}],
        }
    ],
}


def test_well_known_url():
    assert well_known_url("example.com") == "https://example.com/.well-known/elci.json"
    assert well_known_url("https://example.com/a/b?c") == "https://example.com/.well-known/elci.json"
    with pytest.raises(ValueError):
        well_known_url("http://example.com")


def test_parse_and_route():
    card = AgentCard.from_dict(CARD)
    assert card.principal == "Test Person"
    assert card.agent_for("collaboration").name == "creator"
    assert card.agent_for("scheduling") is None
    assert card.fallback == "mailto:test@example.com"


def test_rejects_invalid_card():
    bad = {**CARD, "agents": [{**CARD["agents"][0], "endpoint": "http://insecure"}]}
    with pytest.raises(CardError):
        AgentCard.from_dict(bad)
