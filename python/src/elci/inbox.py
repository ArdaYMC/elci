"""Receiving side: the checks every incoming Elçi message must pass, plus a tiny HTTP transport."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit

import jsonschema

from . import _schemas
from .card import AgentCard
from .crypto import SignatureError, verify_delegation, verify_message

CardResolver = Callable[[str], AgentCard]  # domain -> card
KeyFetcher = Callable[[str], list[dict]]  # jwks_uri -> keys


class Rejected(ValueError):
    """The message failed a protocol check. ``status`` is the HTTP code to answer with."""

    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.status = status


def fetch_jwks(uri: str) -> list[dict]:
    with urllib.request.urlopen(uri, timeout=10) as resp:  # noqa: S310 - https enforced by schema
        return json.load(resp)["keys"]


def fetch_card(domain: str) -> AgentCard:
    from .card import well_known_url

    with urllib.request.urlopen(well_known_url(domain), timeout=10) as resp:  # noqa: S310
        return AgentCard.from_dict(json.load(resp))


class Inbox:
    """Verifies messages addressed to one principal's public agents."""

    def __init__(self, own_card: AgentCard, resolve_card: CardResolver = fetch_card,
                 fetch_keys: KeyFetcher = fetch_jwks, now: Callable[[], int] | None = None):
        self.own_card = own_card
        self.resolve_card = resolve_card
        self.fetch_keys = fetch_keys
        self.now = now
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def accept(self, message: dict) -> dict:
        try:
            jsonschema.validate(message, _schemas.load("message.schema.json"))
        except jsonschema.ValidationError as exc:
            raise Rejected(f"invalid message: {exc.message}") from exc

        recipient = self.own_card.agent(message["to"])
        if recipient is None:
            raise Rejected("no such agent here", 404)
        if message["topic"] not in recipient.topics:
            raise Rejected(f"agent does not accept topic {message['topic']!r}", 403)

        try:
            sender_card = self.resolve_card(message["on_behalf_of"])
        except Exception as exc:  # network or schema failure
            raise Rejected(f"cannot resolve sender card: {exc}", 401) from exc
        sender = sender_card.agent(message["from"])
        if sender is None:
            raise Rejected("sender agent is not listed in its principal's card", 401)
        keys = list(sender.keys) or self.fetch_keys(sender.jwks_uri)

        try:
            verify_message(message, keys)
            if "delegation" not in message:
                raise SignatureError("missing delegation token")
            verify_delegation(message["delegation"], sender_card.principal_keys, agent=sender.id,
                              topic=message["topic"], intent=message["intent"],
                              now=self.now() if self.now else None)
        except SignatureError as exc:
            raise Rejected(str(exc), 401) from exc

        with self._lock:
            if message["signature"] in self._seen:
                raise Rejected("replayed message", 409)
            self._seen.add(message["signature"])
        return message


def serve(inbox: Inbox, handle: Callable[[dict], dict | None], host: str = "127.0.0.1",
          port: int = 0) -> ThreadingHTTPServer:
    """Start a background HTTP server that runs ``inbox.accept`` then ``handle`` on each POST.

    Production deployments sit behind HTTPS (spec requires https endpoints); this server is for
    local development, tests and demos.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length", "0"))
                message = json.loads(self.rfile.read(length) or b"{}")
                inbox.accept(message)
                reply = handle(message)
                self._send(202, {"status": "accepted", "reply": reply})
            except Rejected as exc:
                self._send(exc.status, {"status": "rejected", "reason": str(exc)})
            except json.JSONDecodeError:
                self._send(400, {"status": "rejected", "reason": "body is not JSON"})

        def _send(self, code: int, payload: dict):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # keep test output quiet
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def send(message: dict, endpoint: str, *, allow_insecure_localhost: bool = False) -> tuple[int, dict]:
    parts = urlsplit(endpoint)
    local = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if parts.scheme != "https" and not (allow_insecure_localhost and local):
        raise ValueError("Elçi endpoints must use https")
    req = urllib.request.Request(endpoint, data=json.dumps(message).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        return err.code, json.load(err)
