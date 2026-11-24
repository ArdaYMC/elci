"""The Cloudflare relay's logic (run on Node) and the Python CLI agree on the wire format."""

import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from elci import cli
from elci.home import Home
from elci.store import Store

RELAY = Path(__file__).resolve().parents[2] / "templates" / "cloudflare"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")


@pytest.fixture
def relay():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(["node", "test/serve-local.mjs", str(port), "tok-123"], cwd=RELAY,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "ready"
    yield port
    proc.terminate()
    proc.wait(timeout=5)


def call(port, host, method, path, payload=None, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"Host": host, "Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_publish_queue_and_pull_through_the_relay(relay, tmp_path, monkeypatch):
    monkeypatch.setenv("ELCI_PASSPHRASE", "")
    me, them = tmp_path / "me", tmp_path / "them"
    cli.main(["--home", str(me), "init", "--name", "Me", "--domain", "me.workers.dev", "--agent", "assistant:scheduling"])
    cli.main(["--home", str(them), "init", "--name", "Them", "--domain", "them.example", "--agent", "bot:scheduling"])
    cli.main(["--home", str(me), "relay", "--token", "tok-123", "--show-token"])

    def over_http(relay_cfg, method, path, payload=None):
        status, body = call(relay, relay_cfg["domain"], method, path, payload, relay_cfg["token"])
        assert status < 300, (status, body)
        return body

    monkeypatch.setattr(cli, "_relay_call", over_http)
    assert cli.main(["--home", str(me), "relay"]) == 0
    status, card = call(relay, "me.workers.dev", "GET", "/.well-known/elci.json")
    assert status == 200 and card["principal"]["domain"] == "me.workers.dev"

    my_agent = Home(me).card().agents[0]
    msg = Home(them).agent().message(to=my_agent.id, topic="scheduling", intent="propose", body={"slots": ["Thu"]})
    assert call(relay, "me.workers.dev", "POST", "/inbox/assistant", msg)[0] == 202
    assert call(relay, "me.workers.dev", "POST", "/inbox/assistant", {**msg, "to": "https://x.example/a"})[0] == 400

    cards = {"me.workers.dev": Home(me).card(), "them.example": Home(them).card()}
    monkeypatch.setattr(cli, "CardCache", lambda: cards.__getitem__)
    assert cli.main(["--home", str(me), "pull"]) == 0
    received = Store(Home(me).store_path).received()
    assert [r["message"] for r in received] == [msg]
    assert abs(received[0]["received_at"] - time.time()) < 60
    assert call(relay, "me.workers.dev", "GET", "/admin/messages", token="tok-123")[1] == []
