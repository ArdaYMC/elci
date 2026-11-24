"""Every outgoing request names itself: Cloudflare answers 403 to the default Python-urllib agent."""

import io
import json
import urllib.request

import elci
from elci import cli, inbox


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_user_agent_names_elci_and_version():
    assert inbox.USER_AGENT.startswith(f"elci/{elci.__version__}")
    assert ("User-Agent", inbox.USER_AGENT) in inbox._opener.addheaders


def test_send_sets_user_agent(monkeypatch):
    seen = {}

    def fake_open(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        return _Resp(b"{}")

    monkeypatch.setattr(inbox._opener, "open", fake_open)
    status, _ = inbox.send({"x": 1}, "https://peer.example/inbox/a")
    assert status == 200 and seen["ua"] == inbox.USER_AGENT


def test_relay_call_sets_user_agent(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        return _Resp(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert cli._relay_call({"domain": "x.workers.dev", "token": "t"}, "GET", "/admin/messages") == {"ok": True}
    assert seen["ua"] == inbox.USER_AGENT
