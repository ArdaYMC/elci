"""MCP server: lets any MCP host (Claude Code, Claude Desktop, ...) use Elçi.

Configure with environment variables:

  ELCI_AGENT_ID          https URL of this agent, as listed in your principal card
  ELCI_PRINCIPAL_DOMAIN  your domain (the card lives at https://<domain>/.well-known/elci.json)
  ELCI_AGENT_KEY_HEX     32-byte Ed25519 seed of the agent key, hex (keep it in a secret store)
  ELCI_DELEGATION        delegation token your principal key issued to this agent

Run:  elci-mcp            (stdio)

Binding intents (``accept``) are refused unless a principal-signed approval receipt is passed in;
an agent cannot approve on its own.
"""

from __future__ import annotations

import os
from email import policy
from email.parser import BytesParser

from .card import AgentCard
from .crypto import BINDING_INTENTS
from .disclosure import DisclosurePolicy
from .fallback import compose_fallback_email, parse_reply
from .inbox import fetch_card, send


def _agent():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from .agent import Agent

    missing = [v for v in ("ELCI_AGENT_ID", "ELCI_PRINCIPAL_DOMAIN", "ELCI_AGENT_KEY_HEX", "ELCI_DELEGATION")
               if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"set {', '.join(missing)} to send messages")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(os.environ["ELCI_AGENT_KEY_HEX"]))
    return Agent(os.environ["ELCI_AGENT_ID"], os.environ["ELCI_PRINCIPAL_DOMAIN"], key,
                 os.environ["ELCI_DELEGATION"])


# Plain functions, so they are testable without an MCP host.

def discover(domain: str, resolve=fetch_card) -> dict:
    card: AgentCard = resolve(domain)
    return {
        "principal": card.principal,
        "domain": card.domain,
        "fallback": card.fallback,
        "agents": [{"id": a.id, "name": a.name, "topics": list(a.topics)} for a in card.agents],
    }


def route(domain: str, topic: str, resolve=fetch_card) -> dict:
    """Which agent to contact for ``topic`` at ``domain``, or the email fallback."""
    card = resolve(domain)
    agent = card.agent_for(topic)
    if agent:
        return {"via": "agent", "agent_id": agent.id, "endpoint": agent.endpoint}
    return {"via": "email", "address": (card.fallback or "").removeprefix("mailto:") or None}


def send_message(domain: str, to_agent_id: str, topic: str, intent: str, body: dict,
                 thread: str | None = None, approval: dict | None = None, resolve=fetch_card) -> dict:
    if intent in BINDING_INTENTS and approval is None:
        return {"sent": False, "reason": f"{intent!r} needs a principal-signed approval receipt"}
    card = resolve(domain)
    target = card.agent(to_agent_id)
    if target is None:
        return {"sent": False, "reason": "agent not listed in that card"}
    message = _agent().message(to=to_agent_id, topic=topic, intent=intent, body=body, thread=thread,
                               approval=approval)
    status, reply = send(message, target.endpoint)
    return {"sent": status == 202, "status": status, "reply": reply, "thread": message["thread"]}


def draft_email(to_address: str, topic: str, sender_name: str, options: list[str] | None = None,
                note: str | None = None, thread: str | None = None) -> dict:
    """Draft (never send) a fallback email for someone without an agent."""
    import secrets

    message = {"topic": topic, "thread": thread or f"thr_{secrets.token_hex(6)}",
               "body": {"slots": options or [], **({"note": note} if note else {})}}
    email = compose_fallback_email(message, from_addr="", to_addr=to_address, sender_name=sender_name)
    return {"to": to_address, "subject": email["Subject"], "body": email.get_content(),
            "thread": message["thread"]}


def read_email_reply(raw_email: str) -> dict:
    parsed = parse_reply(raw_email.encode("utf-8"))
    return {"thread": parsed.thread, "choice": parsed.choice, "accepted": parsed.accepted,
            "declined": parsed.declined, "text": parsed.text, "needs_confirmation": parsed.needs_confirmation}


def redact_availability(records: list[dict], level: str = "busy_free") -> list[dict]:
    policy_ = DisclosurePolicy(allowed={"availability": level})
    return [policy_.redact(r) for r in records]


def build_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="elci",
        instructions="Talk to other people's agents with Elçi. Discover a person's agents by domain, "
                     "share availability only at the allowed level, draft emails for people without "
                     "an agent. Never send a binding 'accept' without the human's signed approval.",
    )
    for fn in (discover, route, send_message, draft_email, read_email_reply, redact_availability):
        server.tool()(_without_resolver(fn))
    return server


def _without_resolver(fn):
    """Hide the test-only ``resolve`` parameter from the tool schema."""
    import functools
    import inspect

    sig = inspect.signature(fn)
    if "resolve" not in sig.parameters:
        return fn

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    wrapper.__signature__ = sig.replace(parameters=[p for n, p in sig.parameters.items() if n != "resolve"])
    return wrapper


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
