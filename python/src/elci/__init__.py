"""Elçi: an open person-to-person agent protocol (reference implementation)."""

from .agent import Agent
from .card import AgentCard, AgentEntry, CardError, well_known_url
from .crypto import (
    Delegation,
    SignatureError,
    issue_approval,
    issue_delegation,
    public_jwk,
    sign_message,
    verify_approval,
    verify_delegation,
    verify_message,
)
from .disclosure import LEVELS, DisclosurePolicy
from .fallback import compose_fallback_email, parse_reply
from .inbox import Inbox, Rejected

__all__ = [
    "Agent",
    "Inbox",
    "Rejected",
    "compose_fallback_email",
    "parse_reply",
    "AgentCard",
    "AgentEntry",
    "CardError",
    "Delegation",
    "SignatureError",
    "issue_approval",
    "issue_delegation",
    "public_jwk",
    "sign_message",
    "verify_approval",
    "verify_delegation",
    "verify_message",
    "DisclosurePolicy",
    "LEVELS",
    "well_known_url",
]
__version__ = "0.0.5"
