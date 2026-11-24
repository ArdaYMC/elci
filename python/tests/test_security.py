"""Regression tests for the 2026-11 security review. Each test is one attack that used to work."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from conftest import make_principal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from elci import Agent, AgentCard, Delegation, Inbox, Rejected, issue_approval, issue_delegation, public_jwk
from elci.crypto import SignatureError, b64u, b64u_decode, canonical, verify_delegation
from elci.inbox import fetch_card, is_domain_name

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def inbox_for(cards, domain, **kw):
    return Inbox(cards[domain], resolve_card=cards.__getitem__, fetch_keys=lambda uri: [], **kw)


# --- replay -------------------------------------------------------------------

def _reencodings(sig: str):
    last = ALPHABET.index(sig[-1])
    return [sig + "!!!!", sig[:-1] + ALPHABET[last ^ 1], sig[:10] + "\n" + sig[10:], sig + "=="]


def test_reencoded_signature_is_not_a_fresh_message(pair):
    cards, creator, brand = pair
    inbox = inbox_for(cards, "creator.example")
    msg = brand.message(to=creator.id, topic="collaboration", intent="propose", body={})
    inbox.accept(msg)
    for variant in _reencodings(msg["signature"]):
        with pytest.raises(Rejected) as exc:
            inbox.accept({**msg, "signature": variant})
        assert exc.value.status in (401, 409)


def test_b64u_decode_is_strict():
    assert b64u_decode(b64u(b"\x00" * 64)) == b"\x00" * 64
    for bad in ["AA==", "AB", "A!AA", "A", "AA AA"]:
        with pytest.raises(SignatureError):
            b64u_decode(bad)


def _stamp(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize("delta", [timedelta(minutes=-10), timedelta(minutes=10)])
def test_stale_or_future_messages_are_rejected(pair, delta):
    cards, creator, brand = pair
    msg = brand.message(to=creator.id, topic="collaboration", intent="propose", body={}, created_at=_stamp(delta))
    with pytest.raises(Rejected, match="too old"):
        inbox_for(cards, "creator.example").accept(msg)


def test_replay_cache_forgets_only_after_the_window(pair):
    cards, creator, brand = pair
    clock = [time.time()]
    inbox = inbox_for(cards, "creator.example", now=lambda: clock[0])
    msg = brand.message(to=creator.id, topic="collaboration", intent="propose", body={})
    inbox.accept(msg)
    clock[0] += 400  # past max_age: the entry is pruned, but the message is now too old anyway
    with pytest.raises(Rejected, match="too old"):
        inbox.accept(msg)


# --- approval receipts ---------------------------------------------------------

def test_approval_covers_only_the_approved_body():
    a_card, a, _ = make_principal("a.example", "x", ("collaboration",), ("propose",))
    b_card, b, b_pkey = make_principal("b.example", "y", ("collaboration",), ("accept",))
    cards = {"a.example": a_card, "b.example": b_card}
    approved = {"slot": 1, "price": 100}
    receipt = issue_approval(b_pkey, principal="b.example", thread="thr_00000001", intent="accept",
                             body=approved, summary="slot 1, 100")
    inbox = inbox_for(cards, "a.example")
    inbox.accept(b.message(to=a.id, topic="collaboration", intent="accept", body=approved,
                           thread="thr_00000001", approval=receipt))
    swapped = b.message(to=a.id, topic="collaboration", intent="accept", body={"slot": 3, "price": 9999},
                        thread="thr_00000001", approval=receipt)
    with pytest.raises(Rejected, match="body"):
        inbox.accept(swapped)


# --- origin binding ------------------------------------------------------------

def _impostor_card(served_from: str, claimed_domain: str, agent_id: str, iss: str):
    pk, ak = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    card = AgentCard.from_dict({
        "protocol_version": "0.0.2",
        "principal": {"name": "Bank", "domain": claimed_domain, "jwks": {"keys": [public_jwk(pk.public_key())]}},
        "agents": [{"id": agent_id, "topics": ["collaboration"], "endpoint": f"https://{served_from}/e",
                    "jwks": {"keys": [public_jwk(ak.public_key())]}}],
    })
    token = issue_delegation(Delegation(iss, agent_id, ("collaboration",), ("propose",), int(time.time()) + 3600), pk)
    return card, Agent(agent_id, served_from, ak, token)


@pytest.mark.parametrize("claimed_domain, agent_id, iss, reason", [
    ("bank.example", "https://evil.example/a", "evil.example", "different domain"),
    ("evil.example", "https://bank.example/a", "evil.example", "not on its principal"),
    ("evil.example", "https://evil.example/a", "bank.example", "different principal"),
])
def test_a_card_cannot_speak_for_another_domain(claimed_domain, agent_id, iss, reason):
    c_card, creator, _ = make_principal("creator.example", "creator", ("collaboration",), ("propose",))
    evil_card, evil = _impostor_card("evil.example", claimed_domain, agent_id, iss)
    cards = {"creator.example": c_card, "evil.example": evil_card}
    msg = evil.message(to=creator.id, topic="collaboration", intent="propose", body={})
    with pytest.raises(Rejected, match=reason):
        inbox_for(cards, "creator.example").accept(msg)


def test_agents_on_a_subdomain_are_fine():
    c_card, creator, _ = make_principal("creator.example", "creator", ("collaboration",), ("propose",))
    card, agent = _impostor_card("brand.example", "brand.example", "https://agents.brand.example/a", "brand.example")
    cards = {"creator.example": c_card, "brand.example": card}
    inbox_for(cards, "creator.example").accept(agent.message(to=creator.id, topic="collaboration",
                                                             intent="propose", body={}))


# --- SSRF and error hygiene ----------------------------------------------------

@pytest.mark.parametrize("target", ["127.0.0.1", "127.0.0.1:6379", "0x7f.1", "localhost", "169.254.169.254",
                                    "user@internal.example", "internal.example/x?", "[::1]"])
def test_sender_domain_must_be_a_plain_dns_name(pair, target):
    cards, creator, brand = pair
    msg = {**brand.message(to=creator.id, topic="collaboration", intent="propose", body={}), "on_behalf_of": target}
    with pytest.raises(Rejected):
        inbox_for(cards, "creator.example").accept(msg)
    assert not is_domain_name(target)
    with pytest.raises(ValueError):
        fetch_card(target)


def test_resolver_errors_are_not_echoed(pair):
    cards, creator, brand = pair

    def resolver(domain):
        raise OSError("10.0.0.7:5432 connection refused")

    inbox = Inbox(cards["creator.example"], resolve_card=resolver)
    with pytest.raises(Rejected) as exc:
        inbox.accept(brand.message(to=creator.id, topic="collaboration", intent="propose", body={}))
    assert "10.0.0.7" not in str(exc.value)


def test_jwks_fetch_failure_is_a_clean_rejection():
    c_card, creator, _ = make_principal("creator.example", "creator", ("collaboration",), ("propose",))
    pk, ak = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    aid = "https://brand.example/a"
    card = AgentCard.from_dict({
        "protocol_version": "0.0.2",
        "principal": {"name": "B", "domain": "brand.example", "jwks": {"keys": [public_jwk(pk.public_key())]}},
        "agents": [{"id": aid, "topics": ["collaboration"], "endpoint": "https://brand.example/e",
                    "jwks_uri": "https://brand.example/keys"}],
    })
    token = issue_delegation(Delegation("brand.example", aid, ("collaboration",), ("propose",), int(time.time()) + 60), pk)
    msg = Agent(aid, "brand.example", ak, token).message(to=creator.id, topic="collaboration", intent="propose", body={})

    def boom(uri):
        raise OSError("internal")

    inbox = Inbox(c_card, resolve_card={"brand.example": card}.__getitem__, fetch_keys=boom)
    with pytest.raises(Rejected, match="cannot fetch sender keys"):
        inbox.accept(msg)


@pytest.mark.parametrize("signature", ["a", "", "####"])
def test_garbage_signatures_are_rejections_not_crashes(pair, signature):
    cards, creator, brand = pair
    msg = {**brand.message(to=creator.id, topic="collaboration", intent="propose", body={}), "signature": signature}
    with pytest.raises(Rejected):
        inbox_for(cards, "creator.example").accept(msg)


# --- delegation hardening ------------------------------------------------------

def _token(header: dict, claims: dict, key) -> str:
    signing_input = f"{b64u(canonical(header))}.{b64u(canonical(claims))}"
    return f"{signing_input}.{b64u(key.sign(signing_input.encode('ascii')))}"


@pytest.mark.parametrize("header, claims", [
    ({"alg": "EdDSA", "typ": "JWT"}, {}),  # wrong typ: some other JWT signed by the same key
    ({"alg": "EdDSA", "typ": "elci-delegation+jwt"}, {"exp": "9999999999"}),
    ({"alg": "EdDSA", "typ": "elci-delegation+jwt"}, {"topics": "collaboration"}),
])
def test_delegation_rejects_wrong_type_and_malformed_claims(header, claims):
    key = Ed25519PrivateKey.generate()
    base = {"iss": "a.example", "sub": "https://a.example/x", "topics": ["collaboration"],
            "intents": ["propose"], "iat": 1, "exp": int(time.time()) + 60}
    token = _token(header, {**base, **claims}, key)
    with pytest.raises(SignatureError):
        verify_delegation(token, [public_jwk(key.public_key())], agent="https://a.example/x",
                          topic="collaboration", intent="propose")


# --- HTTP server ---------------------------------------------------------------

def test_server_refuses_oversized_and_lengthless_bodies(pair):
    import http.client

    from elci.inbox import serve

    cards, creator, brand = pair
    server = serve(inbox_for(cards, "creator.example"), lambda m: None)
    try:
        host, port = server.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.putrequest("POST", "/")
        conn.putheader("Content-Length", str(10 * 1024 * 1024))
        conn.endheaders()
        assert conn.getresponse().status == 413
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.putrequest("POST", "/")
        conn.putheader("Content-Length", "-1")
        conn.endheaders()
        assert conn.getresponse().status == 413
    finally:
        server.shutdown()
