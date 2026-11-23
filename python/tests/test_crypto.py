import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from elci import SignatureError, sign_message, verify_delegation, verify_message
from elci.crypto import canonical

V = json.loads((Path(__file__).resolve().parents[2] / "spec" / "vectors" / "signing.json").read_text("utf-8"))
KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(V["private_seed_hex"]))
JWKS = [V["public_jwk"]]


def test_canonical_form_vector():
    assert canonical(V["message"]["unsigned"]).decode("utf-8") == V["message"]["canonical"]


def test_signature_vector_is_deterministic():
    assert sign_message(V["message"]["unsigned"], KEY)["signature"] == V["message"]["signature"]


def test_verify_signed_message():
    verify_message({**V["message"]["unsigned"], "signature": V["message"]["signature"]}, JWKS)


def test_tampered_message_fails():
    tampered = {**V["message"]["unsigned"], "intent": "accept", "signature": V["message"]["signature"]}
    with pytest.raises(SignatureError):
        verify_message(tampered, JWKS)


def test_wrong_key_fails():
    from elci import public_jwk
    other = public_jwk(Ed25519PrivateKey.generate().public_key())
    with pytest.raises(SignatureError):
        verify_message({**V["message"]["unsigned"], "signature": V["message"]["signature"]}, [other])


def test_unsigned_message_fails():
    with pytest.raises(SignatureError):
        verify_message(V["message"]["unsigned"], JWKS)


@pytest.mark.parametrize("check", V["delegation"]["checks"], ids=lambda c: f"{c['topic']}-{c['intent']}-{c['now']}")
def test_delegation_vector(check):
    kwargs = dict(agent=V["delegation"]["claims"]["sub"], topic=check["topic"], intent=check["intent"], now=check["now"])
    if check["valid"]:
        d = verify_delegation(V["delegation"]["token"], JWKS, **kwargs)
        assert d.principal == V["delegation"]["claims"]["iss"]
    else:
        with pytest.raises(SignatureError):
            verify_delegation(V["delegation"]["token"], JWKS, **kwargs)


def test_delegation_for_other_agent_fails():
    with pytest.raises(SignatureError):
        verify_delegation(V["delegation"]["token"], JWKS, agent="https://evil.example/agent",
                          topic="collaboration", intent="propose", now=1800000000)


def test_forged_delegation_fails():
    h, c, _ = V["delegation"]["token"].split(".")
    forged_sig = sign_message({"x": 1}, Ed25519PrivateKey.generate())["signature"]
    with pytest.raises(SignatureError):
        verify_delegation(f"{h}.{c}.{forged_sig}", JWKS, agent=V["delegation"]["claims"]["sub"],
                          topic="collaboration", intent="propose", now=1800000000)
