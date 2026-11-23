"""Sending side: an agent that builds signed, delegated Elçi messages."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto import sign_message

PROTOCOL_VERSION = "0.0.2"


@dataclass
class Agent:
    id: str  # https URL listed in the principal card
    principal_domain: str
    key: Ed25519PrivateKey
    delegation: str  # token issued by the principal

    def message(self, *, to: str, topic: str, intent: str, body: dict, thread: str | None = None,
                created_at: str | None = None) -> dict:
        msg = {
            "protocol_version": PROTOCOL_VERSION,
            "from": self.id,
            "to": to,
            "on_behalf_of": self.principal_domain,
            "topic": topic,
            "intent": intent,
            "thread": thread or f"thr_{secrets.token_hex(6)}",
            "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "body": body,
            "delegation": self.delegation,
        }
        return sign_message(msg, self.key)
