"""MCP server: lets any MCP host (Claude Code, Claude Desktop, ...) use Elçi.

Configuration, simplest first:

  1. Run ``elci init`` once. The server then uses ``~/.elci`` (or ``ELCI_HOME``); set ``ELCI_AGENT``
     to pick an agent when you have several.
  2. Or set ELCI_AGENT_ID, ELCI_PRINCIPAL_DOMAIN, ELCI_AGENT_KEY_HEX (32-byte Ed25519 seed, hex)
     and ELCI_DELEGATION directly.

Run:  elci-mcp            (stdio)

Binding intents (``accept``) need a receipt signed with the principal key. The server never holds
that key: ``request_approval`` files a request, the human runs ``elci approve <id>`` in a terminal,
and ``send_message(..., approval_id=<id>)`` attaches the signed receipt.
"""

from __future__ import annotations

import os
from email import policy
from email.parser import BytesParser

from .card import AgentCard
from .crypto import BINDING_INTENTS, delegation_claims
from .disclosure import DisclosurePolicy
from .fallback import compose_fallback_email, parse_reply
from .home import Home, default_home
from .inbox import Inbox, Rejected, fetch_card, send
from .store import Store, StoreError

ENV_VARS = ("ELCI_AGENT_ID", "ELCI_PRINCIPAL_DOMAIN", "ELCI_AGENT_KEY_HEX", "ELCI_DELEGATION")


def _home() -> Home:
    return Home(default_home())


def _store() -> Store:
    return Store(_home().store_path)


def _agent():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from .agent import Agent

    if not all(os.environ.get(v) for v in ENV_VARS):
        home = _home()
        if home.exists():
            return home.agent(os.environ.get("ELCI_AGENT") or None)
        raise RuntimeError("run `elci init` first, or set " + ", ".join(ENV_VARS))
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
                 thread: str | None = None, approval_id: str | None = None, resolve=fetch_card,
                 store: Store | None = None) -> dict:
    """Send a signed message to another person's agent. ``accept`` needs ``approval_id``."""
    approval = None
    if intent in BINDING_INTENTS:
        if not approval_id:
            return {"sent": False, "reason": f"{intent!r} is binding: call request_approval first, ask the "
                                             "human to run `elci approve <id>`, then pass approval_id"}
        try:
            approval = (store or _store()).receipt(approval_id, body)
        except StoreError as exc:
            return {"sent": False, "reason": str(exc)}
        if thread is None:
            thread = approval["thread"]
    agent = _agent()
    claims = delegation_claims(agent.delegation)
    if topic not in (claims.get("topics") or []):
        return {"sent": False, "reason": f"this agent may only talk about {', '.join(claims.get('topics') or [])}; "
                                         f"{topic!r} would be rejected (use another agent or add the topic)"}
    if intent not in (claims.get("intents") or []):
        return {"sent": False, "reason": f"this agent may not send {intent!r}"}
    card = resolve(domain)
    target = card.agent(to_agent_id)
    if target is None:
        return {"sent": False, "reason": "agent not listed in that card"}
    message = agent.message(to=to_agent_id, topic=topic, intent=intent, body=body, thread=thread,
                               approval=approval)
    status, response = send(message, target.endpoint)
    store = store or _store()
    store.add_sent(message, status, response)
    out = {"sent": status == 202, "status": status, "reply": response, "thread": message["thread"]}
    answer = response.get("reply") if isinstance(response, dict) else None
    if isinstance(answer, dict):
        out.update(_check_reply(answer, to_agent_id, resolve, store))
    return out


def _check_reply(answer: dict, to_agent_id: str, resolve, store: Store) -> dict:
    """An agent may answer in its HTTP response. Trust that answer only once it verifies like any
    incoming message (signature, delegation, freshness), and only if the agent we wrote to sent it."""
    home = _home()
    if not home.exists():
        return {"reply_verified": None, "reply_problem": "no Elçi home to verify the answer against"}
    try:
        if answer.get("from") != to_agent_id:
            raise Rejected("the answer comes from a different agent")
        Inbox(home.card(), resolve_card=resolve).accept(answer)
    except Rejected as exc:
        return {"reply_verified": False, "reply_problem": str(exc)}
    message_id = store.add_received(answer)
    store.read_received(message_id)
    return {"reply_verified": True, "answer": answer, "answer_id": message_id}


def check_inbox(unread_only: bool = True, store: Store | None = None) -> list[dict]:
    """Messages other agents sent you (already verified on arrival). Newest last."""
    out = []
    for item in (store or _store()).received(unread_only=unread_only):
        m = item["message"]
        out.append({"id": item["id"], "from": m["from"], "on_behalf_of": m["on_behalf_of"], "topic": m["topic"],
                    "intent": m["intent"], "thread": m["thread"], "created_at": m["created_at"],
                    "read": item["read"]})
    return out


def read_message(message_id: str, store: Store | None = None) -> dict:
    """The full message (body included); marks it read."""
    try:
        return (store or _store()).read_received(message_id)["message"]
    except StoreError as exc:
        return {"error": str(exc)}


def request_approval(thread: str, intent: str, body: dict, summary: str, to_agent_id: str | None = None,
                     topic: str | None = None, store: Store | None = None) -> dict:
    """Ask your human to approve one binding step. Returns an id; they approve it in a terminal."""
    agent = _agent()
    approval_id = (store or _store()).request_approval(
        principal=agent.principal_domain, thread=thread, intent=intent, body=body, summary=summary,
        to=to_agent_id, topic=topic, agent=agent.id)
    return {"approval_id": approval_id, "state": "pending",
            "ask_human": f"Please run `elci approve {approval_id}` in a terminal to review and sign: {summary}"}


def approval_status(approval_id: str, store: Store | None = None) -> dict:
    """pending, signed or denied."""
    try:
        request = (store or _store()).approval_request(approval_id)
    except StoreError as exc:
        return {"error": str(exc)}
    return {"approval_id": approval_id, "state": request["state"], "summary": request["summary"]}


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
                     "check_inbox for what others sent, share availability only at the allowed level, "
                     "draft emails for people without an agent. Before any 'accept', call request_approval "
                     "and ask the human to run `elci approve <id>`; never claim approval yourself.",
    )
    for fn in (discover, route, send_message, check_inbox, read_message, request_approval, approval_status,
               draft_email, read_email_reply, redact_availability):
        server.tool()(_without_resolver(fn))
    return server


def _without_resolver(fn):
    """Hide the test-only ``resolve`` and ``store`` parameters from the tool schema."""
    import functools
    import inspect

    hidden = {"resolve", "store"}
    sig = inspect.signature(fn)
    if not hidden & set(sig.parameters):
        return fn

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    wrapper.__signature__ = sig.replace(parameters=[p for n, p in sig.parameters.items() if n not in hidden])
    return wrapper


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
