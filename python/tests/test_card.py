import pytest

from elci import AgentCard, CardError, well_known_url

CARD = {
    "protocol_version": "0.0.2",
    "principal": {"name": "Test Person", "domain": "example.com", "fallback": "mailto:test@example.com"},
    "agents": [
        {
            "id": "https://example.com/agents/creator",
            "name": "creator",
            "topics": ["collaboration"],
            "endpoint": "https://example.com/elci/creator",
            "jwks": {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": "AAAA"}]},
            "a2a_card": "https://example.com/agents/creator/agent-card.json",
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
    assert card.domain == "example.com"
    assert card.agents[0].keys[0]["kty"] == "OKP"


def test_jwks_uri_instead_of_inline_keys():
    agent = {k: v for k, v in CARD["agents"][0].items() if k != "jwks"}
    agent["jwks_uri"] = "https://example.com/jwks.json"
    card = AgentCard.from_dict({**CARD, "agents": [agent]})
    assert card.agents[0].jwks_uri == "https://example.com/jwks.json"
    assert card.agents[0].keys == ()


def test_rejects_both_or_no_keys():
    both = {**CARD["agents"][0], "jwks_uri": "https://example.com/jwks.json"}
    neither = {k: v for k, v in CARD["agents"][0].items() if k != "jwks"}
    for agent in (both, neither):
        with pytest.raises(CardError):
            AgentCard.from_dict({**CARD, "agents": [agent]})


def test_rejects_invalid_card():
    bad = {**CARD, "agents": [{**CARD["agents"][0], "endpoint": "http://insecure"}]}
    with pytest.raises(CardError):
        AgentCard.from_dict(bad)
