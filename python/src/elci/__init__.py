"""Elçi: an open person-to-person agent protocol (reference implementation)."""

from .card import AgentCard, AgentEntry, CardError, well_known_url
from .crypto import (
    Delegation,
    SignatureError,
    issue_delegation,
    public_jwk,
    sign_message,
    verify_delegation,
    verify_message,
)
from .disclosure import LEVELS, DisclosurePolicy

__all__ = [
    "AgentCard",
    "AgentEntry",
    "CardError",
    "Delegation",
    "SignatureError",
    "issue_delegation",
    "public_jwk",
    "sign_message",
    "verify_delegation",
    "verify_message",
    "DisclosurePolicy",
    "LEVELS",
    "well_known_url",
]
__version__ = "0.0.3"
