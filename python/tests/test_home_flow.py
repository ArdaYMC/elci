"""End to end on disk: elci init, inbox store, MCP approvals, key rotation and revocation."""

import json
import stat

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from elci import Inbox, Rejected, mcp_server
from elci import cli
from elci.crypto import delegation_claims
from elci.home import Home, HomeError
from elci.inbox import CardCache
from elci.store import Store


@pytest.fixture
def homes(tmp_path, monkeypatch):
    monkeypatch.setenv("ELCI_PASSPHRASE", "correct horse")
    a = Home(tmp_path / "a")
    a.init(name="Arda", domain="arda.example", agents={"devbyarda": ("collaboration",)}, passphrase="correct horse")
    b = Home(tmp_path / "b")
    b.init(name="Brand", domain="brand.example", agents={"partnerships": ("collaboration",)},
           passphrase="correct horse")
    return a, b


def cards(*homes):
    return {h.card().domain: h.card() for h in homes}


def test_init_writes_private_files_and_a_valid_card(homes):
    a, _ = homes
    for f in [a.config_path, a.path / "principal.pem", a.path / "agents" / "devbyarda.pem"]:
        assert stat.S_IMODE(f.stat().st_mode) == 0o600, f
    assert b"ENCRYPTED" in (a.path / "principal.pem").read_bytes()
    card = a.card()
    assert card.domain == "arda.example"
    assert card.agents[0].endpoint == "https://arda.example/inbox/devbyarda"
    assert card.principal_keys[0]["kid"].startswith("principal-")
    published = json.loads(a.card_path.read_text())
    for key in published["principal"]["jwks"]["keys"] + published["agents"][0]["jwks"]["keys"]:
        assert "d" not in key  # no private parts in the public card


def test_init_refuses_bad_input(tmp_path):
    with pytest.raises(HomeError):
        Home(tmp_path / "x").init(name="X", domain="127.0.0.1", agents={"a": ("t",)}, passphrase=None)
    with pytest.raises(HomeError):
        Home(tmp_path / "y").init(name="X", domain="x.example", agents={}, passphrase=None)


def test_wrong_passphrase_is_refused(homes):
    a, _ = homes
    with pytest.raises(HomeError, match="wrong passphrase"):
        a.principal_key("nope")


def test_message_round_trip_into_the_store_and_mcp_inbox(homes):
    a, b = homes
    msg = b.agent().message(to=a.card().agents[0].id, topic="collaboration", intent="propose",
                            body={"slots": ["Thu 11:00"]})
    Inbox(a.card(), resolve_card=cards(a, b).__getitem__).accept(msg)
    store = Store(a.store_path)
    store.add_received(msg)
    listed = mcp_server.check_inbox(store=store)
    assert [m["intent"] for m in listed] == ["propose"]
    assert mcp_server.read_message(listed[0]["id"], store=store)["body"] == {"slots": ["Thu 11:00"]}
    assert mcp_server.check_inbox(store=store) == []  # now read
    assert "error" in mcp_server.read_message("msg_../../etc", store=store)


def test_accept_goes_through_human_approval(homes, monkeypatch):
    a, b = homes
    monkeypatch.setenv("ELCI_HOME", str(b.path))
    for v in mcp_server.ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    store = Store(b.store_path)
    inbox = Inbox(a.card(), resolve_card=cards(a, b).__getitem__)
    delivered = []
    monkeypatch.setattr(mcp_server, "send", lambda m, endpoint: (202, {"ok": delivered.append(inbox.accept(m))}))
    to = a.card().agents[0].id
    body = {"slot": "Thu 11:00"}

    out = mcp_server.send_message("arda.example", to, "collaboration", "accept", body, resolve=cards(a, b).__getitem__)
    assert not out["sent"] and "request_approval" in out["reason"]

    req = mcp_server.request_approval("thr_00000001", "accept", body, "Collab Thu 11:00", to_agent_id=to)
    assert "elci approve" in req["ask_human"]
    early = mcp_server.send_message("arda.example", to, "collaboration", "accept", body,
                                    approval_id=req["approval_id"], resolve=cards(a, b).__getitem__)
    assert not early["sent"] and "not approved" in early["reason"]

    assert cli.main(["--home", str(b.path), "approve", req["approval_id"], "--yes"]) == 0
    assert mcp_server.approval_status(req["approval_id"])["state"] == "signed"

    swapped = mcp_server.send_message("arda.example", to, "collaboration", "accept", {"slot": "Fri 09:00"},
                                      approval_id=req["approval_id"], resolve=cards(a, b).__getitem__)
    assert not swapped["sent"] and "different body" in swapped["reason"]

    ok = mcp_server.send_message("arda.example", to, "collaboration", "accept", body,
                                 approval_id=req["approval_id"], resolve=cards(a, b).__getitem__)
    assert ok["sent"] and ok["thread"] == "thr_00000001"
    assert delivered[0]["approval"]["body_sha256"]


def test_deny_and_double_approve(homes):
    _, b = homes
    store = Store(b.store_path)
    rid = store.request_approval(principal="brand.example", thread="thr_00000002", intent="accept",
                                 body={}, summary="x")
    assert cli.main(["--home", str(b.path), "deny", rid]) == 0
    assert cli.main(["--home", str(b.path), "approve", rid, "--yes"]) == 2  # already denied


def test_rotating_an_agent_key_revokes_the_old_one(homes):
    a, b = homes
    to = a.card().agents[0].id
    old_agent = b.agent()
    old_jti = delegation_claims(old_agent.delegation)["jti"]
    b.rotate_agent("partnerships")
    assert old_jti in b.card().revoked
    inbox = Inbox(a.card(), resolve_card=cards(a, b).__getitem__)
    with pytest.raises(Rejected):  # old key no longer in the card
        inbox.accept(old_agent.message(to=to, topic="collaboration", intent="propose", body={}))
    inbox.accept(b.agent().message(to=to, topic="collaboration", intent="propose", body={}))


def test_revoked_delegation_is_refused_even_with_a_valid_key(homes):
    a, b = homes
    jti = delegation_claims(b.agent().delegation)["jti"]
    b.revoke(jti)
    msg = b.agent().message(to=a.card().agents[0].id, topic="collaboration", intent="propose", body={})
    with pytest.raises(Rejected, match="revoked"):
        Inbox(a.card(), resolve_card=cards(a, b).__getitem__).accept(msg)


def test_principal_rotation_invalidates_old_delegations(homes):
    a, b = homes
    old = b.agent()
    b.rotate_principal()
    inbox = Inbox(a.card(), resolve_card=cards(a, b).__getitem__)
    to = a.card().agents[0].id
    with pytest.raises(Rejected):
        inbox.accept(old.message(to=to, topic="collaboration", intent="propose", body={}))
    inbox.accept(b.agent().message(to=to, topic="collaboration", intent="propose", body={}))


def test_card_cache_refetches_once_after_rotation(homes):
    a, b = homes
    live = cards(a, b)
    fetches = []

    def resolve(domain):
        fetches.append(domain)
        return live[domain]

    inbox = Inbox(a.card(), resolve_card=CardCache(resolve, ttl=300, min_refresh=0))
    to = a.card().agents[0].id
    inbox.accept(b.agent().message(to=to, topic="collaboration", intent="propose", body={}))
    b.rotate_agent("partnerships")
    live["brand.example"] = b.card()
    inbox.accept(b.agent().message(to=to, topic="collaboration", intent="propose", body={}))
    assert fetches == ["brand.example", "brand.example"]


def test_card_cache_does_not_refetch_for_every_forgery(homes):
    a, b = homes
    fetches = []
    live = cards(a, b)
    inbox = Inbox(a.card(), resolve_card=CardCache(lambda d: fetches.append(d) or live[d], min_refresh=30))
    to = a.card().agents[0].id
    good = b.agent().message(to=to, topic="collaboration", intent="propose", body={})
    for i in range(5):
        forged = {**good, "body": {"n": i}}
        with pytest.raises(Rejected):
            inbox.accept(forged)
    assert len(fetches) == 1


def test_pull_verifies_relay_messages_at_their_arrival_time(homes, monkeypatch):
    a, b = homes
    cfg = a.config()
    cfg["relay"] = {"domain": "arda.example", "token": "t"}
    a.save_config(cfg)
    good = b.agent().message(to=a.card().agents[0].id, topic="collaboration", intent="propose", body={})
    from datetime import datetime
    arrived = datetime.fromisoformat(good["created_at"].replace("Z", "+00:00")).timestamp() + 10
    queued = [{"id": "q1", "received_at": arrived * 1000, "message": good},
              {"id": "q2", "received_at": arrived * 1000, "message": {**good, "body": {"x": 1}}}]
    acked = []

    def fake(relay, method, path, payload=None):
        if path == "/admin/messages":
            return queued
        acked.extend(payload["ids"])
        return {"deleted": len(payload["ids"])}

    monkeypatch.setattr(cli, "_relay_call", fake)
    monkeypatch.setattr(cli, "CardCache", lambda: cards(a, b).__getitem__)
    assert cli.main(["--home", str(a.path), "pull"]) == 0
    assert acked == ["q1", "q2"]
    assert len(Store(a.store_path).received()) == 1


def test_cli_status_and_card(homes, capsys):
    a, _ = homes
    assert cli.main(["--home", str(a.path), "status"]) == 0
    assert "devbyarda: delegation dlg_" in capsys.readouterr().out
    assert cli.main(["--home", str(a.path), "card"]) == 0
    assert json.loads(capsys.readouterr().out)["principal"]["domain"] == "arda.example"


def test_cli_init_via_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ELCI_PASSPHRASE", "")
    rc = cli.main(["--home", str(tmp_path / "h"), "init", "--name", "Test", "--domain", "t.example",
                   "--agent", "assistant:scheduling,collaboration", "--email", "me@t.example"])
    assert rc == 0
    card = Home(tmp_path / "h").card()
    assert card.agents[0].topics == ("scheduling", "collaboration")
    assert card.fallback == "mailto:me@t.example"
    assert b"ENCRYPTED" not in (tmp_path / "h" / "principal.pem").read_bytes()
    assert cli.main(["--home", str(tmp_path / "h"), "init", "--name", "T", "--domain", "t.example",
                     "--agent", "a:b"]) == 2  # already exists


def test_add_agent_with_narrow_intents_and_export(tmp_path, monkeypatch):
    import pytest

    from elci.home import Home, HomeError

    monkeypatch.setenv("ELCI_PASSPHRASE", "")
    home = Home(tmp_path / "h")
    home.init(name="A", domain="a.example", agents={"assistant": ("scheduling",)}, passphrase=None)
    with pytest.raises(HomeError):
        home.add_agent("demo", ("demo",), intents=["answer", "pay"])
    home.add_agent("demo", ("demo",), intents=["needs_human", "answer"])
    data = home.export_agent("demo")
    assert data["intents"] == ["answer", "needs_human"]
    assert data["endpoint"] == "https://a.example/inbox/demo" and "d" in data["jwk"]
    assert all("d" not in k for a in home.build_card()["agents"] for k in a["jwks"]["keys"])


def test_send_message_refuses_a_topic_outside_the_agents_delegation(tmp_path, monkeypatch):
    from elci import mcp_server
    from elci.home import Home

    monkeypatch.setenv("ELCI_PASSPHRASE", "")
    Home(tmp_path / "h").init(name="A", domain="a.example", agents={"bot": ("test",)}, passphrase=None)
    monkeypatch.setenv("ELCI_HOME", str(tmp_path / "h"))
    monkeypatch.delenv("ELCI_AGENT", raising=False)

    def never(_):
        raise AssertionError("must not even look up the receiver")

    out = mcp_server.send_message("b.example", "https://b.example/agents/x", "scheduling", "query", {}, resolve=never)
    assert out["sent"] is False and "scheduling" in out["reason"]
