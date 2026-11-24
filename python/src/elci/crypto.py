"""Signing and delegation for Elçi messages (Ed25519, JWS compact serialization)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class SignatureError(ValueError):
    """A signature or delegation token did not verify."""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


_B64U_RE = re.compile(r"[A-Za-z0-9_-]*")


def b64u_decode(text: str) -> bytes:
    """Strict base64url (no padding) decoding.

    Rejects padding, characters outside the alphabet and non-zero trailing bits, so every byte
    string has exactly one accepted encoding. Lenient decoders let an attacker re-encode a captured
    signature into endless distinct strings that all verify.
    """
    if not isinstance(text, str) or not _B64U_RE.fullmatch(text) or len(text) % 4 == 1:
        raise SignatureError("not canonical base64url")
    data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if b64u(data) != text:
        raise SignatureError("not canonical base64url")
    return data


def body_digest(obj: object) -> str:
    """base64url SHA-256 of the canonical JSON of ``obj``; binds approval receipts to a message body."""
    return b64u(hashlib.sha256(canonical(obj)).digest())


def canonical(obj: object) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8 (a JCS subset without floats)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# --- keys -------------------------------------------------------------------

def public_jwk(key: Ed25519PublicKey, kid: str | None = None) -> dict:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    raw = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": b64u(raw)}
    if kid:
        jwk["kid"] = kid
    return jwk


def key_from_jwk(jwk: dict) -> Ed25519PublicKey:
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        raise SignatureError("only Ed25519 (kty=OKP, crv=Ed25519) keys are supported")
    return Ed25519PublicKey.from_public_bytes(b64u_decode(jwk["x"]))


def _verify_any(keys: Iterable[dict], signature: bytes, data: bytes, kid: str | None) -> None:
    candidates = [k for k in keys if kid is None or k.get("kid") in (None, kid)]
    for jwk in candidates:
        try:
            key_from_jwk(jwk).verify(signature, data)
            return
        except (InvalidSignature, SignatureError):
            continue
    raise SignatureError("no key in the set verifies this signature")


# --- detached message signatures ---------------------------------------------

def sign_message(message: dict, key: Ed25519PrivateKey) -> dict:
    """Return a copy of ``message`` with ``signature`` over its canonical form."""
    body = {k: v for k, v in message.items() if k != "signature"}
    return {**body, "signature": b64u(key.sign(canonical(body)))}


def verify_message(message: dict, keys: Iterable[dict]) -> None:
    """Raise SignatureError unless some key in ``keys`` signed ``message``."""
    if not isinstance(message.get("signature"), str):
        raise SignatureError("message is not signed")
    body = {k: v for k, v in message.items() if k != "signature"}
    _verify_any(keys, b64u_decode(message["signature"]), canonical(body), None)


# --- delegation tokens (compact JWS, alg EdDSA) -------------------------------

@dataclass(frozen=True)
class Delegation:
    principal: str  # iss: the principal's domain
    agent: str  # sub: the agent id URL
    topics: tuple[str, ...]
    intents: tuple[str, ...]
    expires_at: int  # exp, unix seconds


def issue_delegation(d: Delegation, principal_key: Ed25519PrivateKey, kid: str | None = None,
                     now: int | None = None) -> str:
    header = {"alg": "EdDSA", "typ": "elci-delegation+jwt"}
    if kid:
        header["kid"] = kid
    claims = {
        "iss": d.principal,
        "sub": d.agent,
        "topics": list(d.topics),
        "intents": list(d.intents),
        "iat": int(time.time()) if now is None else now,
        "exp": d.expires_at,
    }
    signing_input = f"{b64u(canonical(header))}.{b64u(canonical(claims))}"
    return f"{signing_input}.{b64u(principal_key.sign(signing_input.encode('ascii')))}"


def verify_delegation(token: str, principal_keys: Iterable[dict], *, agent: str, topic: str,
                      intent: str, principal: str | None = None, now: int | None = None) -> Delegation:
    """Verify a delegation token and that it covers ``agent``, ``topic`` and ``intent``.

    When ``principal`` is given, the token's ``iss`` must name that principal's domain.
    """
    try:
        h64, c64, s64 = token.split(".")
        header = json.loads(b64u_decode(h64))
        claims = json.loads(b64u_decode(c64))
    except ValueError as exc:
        raise SignatureError("malformed delegation token") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise SignatureError("malformed delegation token")
    if header.get("alg") != "EdDSA":
        raise SignatureError("delegation must use alg EdDSA")
    if header.get("typ") != "elci-delegation+jwt":
        raise SignatureError("delegation must have typ elci-delegation+jwt")
    _verify_any(principal_keys, b64u_decode(s64), f"{h64}.{c64}".encode("ascii"), header.get("kid"))
    exp, topics, intents = claims.get("exp"), claims.get("topics"), claims.get("intents")
    if (not isinstance(exp, int) or isinstance(exp, bool) or not isinstance(claims.get("iss"), str)
            or not isinstance(topics, list) or not isinstance(intents, list)):
        raise SignatureError("malformed delegation claims")
    current = int(time.time()) if now is None else now
    if exp <= current:
        raise SignatureError("delegation expired")
    if principal is not None and claims["iss"].lower() != principal.lower():
        raise SignatureError("delegation was issued by a different principal")
    if claims.get("sub") != agent:
        raise SignatureError("delegation was issued to a different agent")
    if topic not in claims.get("topics", []):
        raise SignatureError(f"delegation does not cover topic {topic!r}")
    if intent not in claims.get("intents", []):
        raise SignatureError(f"delegation does not cover intent {intent!r}")
    return Delegation(claims["iss"], claims["sub"], tuple(claims["topics"]),
                      tuple(claims["intents"]), claims["exp"])


# --- human approval receipts ------------------------------------------------------

BINDING_INTENTS = frozenset({"accept"})


def issue_approval(principal_key: Ed25519PrivateKey, *, principal: str, thread: str, intent: str,
                   body: dict, summary: str, now: int | None = None) -> dict:
    """A receipt, signed by the principal's key, that a human approved one binding step.

    ``body`` is the exact message body the human approved; the receipt only covers that body.
    """
    receipt = {
        "type": "elci-approval",
        "principal": principal,
        "thread": thread,
        "intent": intent,
        "body_sha256": body_digest(body),
        "summary": summary,
        "approved_at": int(time.time()) if now is None else now,
    }
    return sign_message(receipt, principal_key)


def verify_approval(receipt: dict, principal_keys: Iterable[dict], *, principal: str, thread: str,
                    intent: str, body: dict) -> None:
    if not isinstance(receipt, dict) or receipt.get("type") != "elci-approval":
        raise SignatureError("missing or malformed approval receipt")
    verify_message(receipt, principal_keys)
    if (receipt.get("principal"), receipt.get("thread"), receipt.get("intent")) != (principal, thread, intent):
        raise SignatureError("approval receipt is for a different principal, thread or intent")
    if receipt.get("body_sha256") != body_digest(body):
        raise SignatureError("approval receipt does not cover this message body")
