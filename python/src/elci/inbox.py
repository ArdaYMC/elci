"""Receiving side: the checks every incoming Elçi message must pass, plus a tiny HTTP transport."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit

import jsonschema

from . import _schemas
from .card import AgentCard
from .crypto import (
    BINDING_INTENTS,
    SignatureError,
    canonical,
    verify_approval,
    verify_delegation,
    verify_message,
)

CardResolver = Callable[[str], AgentCard]  # domain -> card
KeyFetcher = Callable[[str], list[dict]]  # jwks_uri -> keys


class Rejected(ValueError):
    """The message failed a protocol check. ``status`` is the HTTP code to answer with."""

    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.status = status


MAX_DOCUMENT_BYTES = 64 * 1024  # cards and key sets are small; refuse anything bigger
MAX_MESSAGE_BYTES = 256 * 1024
# Labels of letters, digits and hyphens; the last label starts with a letter, which also rules out
# IP literals in every notation (127.0.0.1, 0x7f.1, 2130706433).
_HOSTNAME_RE = re.compile(r"(?=.{1,253}$)((?!-)[a-z0-9-]{1,63}(?<!-)\.)+[a-z][a-z0-9-]{0,62}(?<!-)")


def is_domain_name(value: str) -> bool:
    """True for a plain DNS name such as ``arda.example``: no scheme, port, path, user or IP literal."""
    if not isinstance(value, str) or not _HOSTNAME_RE.fullmatch(value.lower()):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return True
    return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102 - never follow, a redirect could leave https
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _fetch_json(url: str) -> object:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or not is_domain_name(parts.hostname):
        raise ValueError("only https URLs on a DNS name are fetched")
    with _opener.open(url, timeout=10) as resp:  # noqa: S310 - https checked above
        data = resp.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("document too large")
    return json.loads(data)


def fetch_jwks(uri: str) -> list[dict]:
    keys = _fetch_json(uri)["keys"]
    if not isinstance(keys, list):
        raise ValueError("keys must be a list")
    return keys


def fetch_card(domain: str) -> AgentCard:
    if not is_domain_name(domain):
        raise ValueError("a principal is named by its DNS domain")
    return AgentCard.from_dict(_fetch_json(f"https://{domain.lower()}/.well-known/elci.json"))


def _host_in_domain(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class Inbox:
    """Verifies messages addressed to one principal's public agents.

    ``max_age`` and ``max_skew`` (seconds) bound how old, or how far in the future, a message's
    ``created_at`` may be. The replay cache only has to remember that window.
    """

    def __init__(self, own_card: AgentCard, resolve_card: CardResolver = fetch_card,
                 fetch_keys: KeyFetcher = fetch_jwks, now: Callable[[], int] | None = None,
                 max_age: int = 300, max_skew: int = 60):
        self.own_card = own_card
        self.resolve_card = resolve_card
        self.fetch_keys = fetch_keys
        self.now = now
        self.max_age = max_age
        self.max_skew = max_skew
        self._seen: dict[str, float] = {}  # message digest -> created_at
        self._lock = threading.Lock()

    def _clock(self) -> float:
        return self.now() if self.now else time.time()

    def accept(self, message: dict, *, received_at: float | None = None) -> dict:
        """Verify ``message``; return it or raise Rejected.

        ``received_at`` (unix seconds) is when a relay you trust queued the message. Use it when
        you pull messages later, so the freshness window is measured at arrival, not at pull time.
        """
        current = self._clock() if received_at is None else received_at
        try:
            return self._accept(message, current)
        except Rejected:
            raise
        except SignatureError as exc:
            raise Rejected(str(exc), 401) from exc
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise Rejected("malformed message") from exc

    def _sender(self, principal: str, agent_id: str):
        try:
            card = self.resolve_card(principal)
        except Exception as exc:  # network or schema failure; details stay on this side
            raise Rejected("cannot resolve sender card", 401) from exc
        if card.domain.lower() != principal.lower():
            raise Rejected("sender card is for a different domain", 401)
        sender = card.agent(agent_id)
        if sender is None:
            raise Rejected("sender agent is not listed in its principal's card", 401)
        if sender.keys:
            return card, sender, list(sender.keys)
        try:
            return card, sender, self.fetch_keys(sender.jwks_uri)
        except Exception as exc:
            raise Rejected("cannot fetch sender keys", 401) from exc

    def _accept(self, message: dict, current: float) -> dict:
        try:
            jsonschema.validate(message, _schemas.load("message.schema.json"))
        except jsonschema.ValidationError as exc:
            raise Rejected(f"invalid message: {exc.message}") from exc

        principal = message["on_behalf_of"]
        if not is_domain_name(principal):
            raise Rejected("on_behalf_of must be a DNS domain")
        if not _host_in_domain(message["from"], principal):
            raise Rejected("sender agent id is not on its principal's domain", 401)
        created = _timestamp(message["created_at"])
        if created < current - self.max_age or created > current + self.max_skew:
            raise Rejected("message is too old or from the future", 401)

        recipient = self.own_card.agent(message["to"])
        if recipient is None:
            raise Rejected("no such agent here", 404)
        if message["topic"] not in recipient.topics:
            raise Rejected(f"agent does not accept topic {message['topic']!r}", 403)

        sender_card, sender, keys = self._sender(principal, message["from"])
        try:
            verify_message(message, keys)
        except SignatureError:
            # The sender may have rotated its key since the card was cached: refetch it once.
            invalidate = getattr(self.resolve_card, "invalidate", None)
            if invalidate is None:
                raise
            invalidate(principal)
            sender_card, sender, keys = self._sender(principal, message["from"])
            verify_message(message, keys)
        if "delegation" not in message:
            raise SignatureError("missing delegation token")
        verify_delegation(message["delegation"], sender_card.principal_keys, agent=sender.id,
                          topic=message["topic"], intent=message["intent"], principal=principal,
                          now=int(current), revoked=sender_card.revoked)
        if message["intent"] in BINDING_INTENTS:
            verify_approval(message.get("approval"), sender_card.principal_keys, principal=principal,
                            thread=message["thread"], intent=message["intent"], body=message["body"])

        # Replay key: the signed content itself, so re-encoding the signature cannot dodge it.
        digest = hashlib.sha256(canonical({k: v for k, v in message.items() if k != "signature"})).hexdigest()
        with self._lock:
            horizon = current - self.max_age
            for key in [k for k, t in self._seen.items() if t < horizon]:
                del self._seen[key]
            if digest in self._seen:
                raise Rejected("replayed message", 409)
            self._seen[digest] = created
        return message


class CardCache:
    """Card resolver that caches cards for ``ttl`` seconds (spec section 8 caps this at one hour).

    ``Inbox`` calls ``invalidate`` and retries once when a signature fails, so key rotation is
    picked up without waiting for the cache to expire. A card fetched less than ``min_refresh``
    seconds ago is kept, so forged messages cannot make us hammer the sender's server.
    """

    def __init__(self, resolve: CardResolver = fetch_card, ttl: float = 300,
                 clock: Callable[[], float] = time.time, min_refresh: float = 30):
        self.resolve, self.ttl, self.clock = resolve, min(ttl, 3600), clock
        self.min_refresh = min_refresh
        self._cards: dict[str, tuple[float, AgentCard]] = {}
        self._lock = threading.Lock()

    def __call__(self, domain: str) -> AgentCard:
        key = domain.lower()
        with self._lock:
            hit = self._cards.get(key)
        if hit and self.clock() - hit[0] < self.ttl:
            return hit[1]
        card = self.resolve(domain)
        with self._lock:
            self._cards[key] = (self.clock(), card)
        return card

    def invalidate(self, domain: str) -> None:
        with self._lock:
            hit = self._cards.get(domain.lower())
            if hit and self.clock() - hit[0] >= self.min_refresh:
                del self._cards[domain.lower()]


def serve(inbox: Inbox, handle: Callable[[dict], dict | None], host: str = "127.0.0.1",
          port: int = 0) -> ThreadingHTTPServer:
    """Start a background HTTP server that runs ``inbox.accept`` then ``handle`` on each POST.

    Production deployments sit behind HTTPS (spec requires https endpoints); this server is for
    local development, tests and demos.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._send(411, {"status": "rejected", "reason": "Content-Length required"})
            if not 0 < length <= MAX_MESSAGE_BYTES:
                return self._send(413, {"status": "rejected", "reason": "body too large or empty"})
            try:
                message = json.loads(self.rfile.read(length))
                inbox.accept(message)
                reply = handle(message)
                self._send(202, {"status": "accepted", "reply": reply})
            except Rejected as exc:
                self._send(exc.status, {"status": "rejected", "reason": str(exc)})
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"status": "rejected", "reason": "body is not JSON"})
            except Exception:  # never leak internals to the sender
                self._send(500, {"status": "error", "reason": "internal error"})

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
        with _opener.open(req, timeout=10) as resp:  # noqa: S310 - scheme checked above
            return resp.status, json.loads(resp.read(MAX_DOCUMENT_BYTES + 1)[:MAX_DOCUMENT_BYTES] or b"{}")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read(MAX_DOCUMENT_BYTES) or b"{}")
        except ValueError:
            return err.code, {}
