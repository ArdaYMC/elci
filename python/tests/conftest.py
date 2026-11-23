"""Shared fixtures: two principals, each with one public agent, keys and delegations."""

import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from elci import Agent, AgentCard, Delegation, issue_delegation, public_jwk


def make_principal(domain: str, agent_name: str, topics: tuple[str, ...], intents: tuple[str, ...],
                   endpoint: str | None = None):
    principal_key = Ed25519PrivateKey.generate()
    agent_key = Ed25519PrivateKey.generate()
    agent_id = f"https://{domain}/agents/{agent_name}"
    card = AgentCard.from_dict({
        "protocol_version": "0.0.2",
        "principal": {"name": domain, "domain": domain, "jwks": {"keys": [public_jwk(principal_key.public_key())]}},
        "agents": [{
            "id": agent_id,
            "name": agent_name,
            "topics": list(topics),
            "endpoint": endpoint or f"https://{domain}/elci/{agent_name}",
            "jwks": {"keys": [public_jwk(agent_key.public_key())]},
        }],
    })
    token = issue_delegation(Delegation(domain, agent_id, topics, intents, int(time.time()) + 3600), principal_key)
    return card, Agent(agent_id, domain, agent_key, token), principal_key


@pytest.fixture
def pair():
    creator_card, creator, _ = make_principal("creator.example", "creator", ("collaboration",), ("propose", "answer"))
    brand_card, brand, _ = make_principal("brand.example", "partnerships", ("collaboration",), ("propose", "accept"))
    cards = {"creator.example": creator_card, "brand.example": brand_card}
    return cards, creator, brand
