"""Agent cards: discovery documents published at /.well-known/elci.json."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

import jsonschema

from . import _schemas

WELL_KNOWN_PATH = "/.well-known/elci.json"


class CardError(ValueError):
    """The card does not match the Elçi agent card schema."""


def well_known_url(domain_or_url: str) -> str:
    """Return the card URL for a domain (``example.com``) or any URL on it."""
    raw = domain_or_url if "://" in domain_or_url else f"https://{domain_or_url}"
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"agent cards are only served over https: {domain_or_url!r}")
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"https://{host}{WELL_KNOWN_PATH}"


@dataclass(frozen=True)
class AgentEntry:
    id: str
    topics: tuple[str, ...]
    endpoint: str
    keys: tuple[dict, ...] = ()
    jwks_uri: str | None = None
    a2a_card: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class AgentCard:
    principal: str
    domain: str
    agents: tuple[AgentEntry, ...]
    fallback: str | None = None
    principal_keys: tuple[dict, ...] = ()
    revoked: tuple[str, ...] = ()  # delegation token ids (jti) revoked before they expire
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentCard":
        try:
            jsonschema.validate(data, _schemas.load("agent-card.schema.json"))
        except jsonschema.ValidationError as exc:
            raise CardError(exc.message) from exc
        agents = tuple(
            AgentEntry(
                id=a["id"],
                topics=tuple(a["topics"]),
                endpoint=a["endpoint"],
                keys=tuple(a.get("jwks", {}).get("keys", ())),
                jwks_uri=a.get("jwks_uri"),
                a2a_card=a.get("a2a_card"),
                name=a.get("name"),
            )
            for a in data["agents"]
        )
        principal = data["principal"]
        return cls(principal["name"], principal["domain"], agents, principal.get("fallback"),
                   tuple(principal.get("jwks", {}).get("keys", ())),
                   tuple(principal.get("revoked", ())), data)

    def agent_for(self, topic: str) -> AgentEntry | None:
        """First public agent that accepts ``topic``; None means use the fallback."""
        return next((a for a in self.agents if topic in a.topics), None)

    def agent(self, agent_id: str) -> AgentEntry | None:
        return next((a for a in self.agents if a.id == agent_id), None)
