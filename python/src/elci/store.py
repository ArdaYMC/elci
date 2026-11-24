"""Local message and approval store: plain JSON files under ``<home>/store``.

``received/``           verified incoming messages (``elci serve`` and ``elci pull`` write here)
``sent/``               messages you sent, with the receiver's answer
``approvals/pending/``  binding steps an agent asked a human to approve
``approvals/signed/``   receipts the human signed with the principal key (``elci approve``)
``approvals/denied/``   requests the human refused
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto import body_digest, canonical, issue_approval


class StoreError(LookupError):
    pass


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_id(item_id: str, prefix: str) -> str:
    if not item_id.startswith(prefix) or not all(c.isalnum() or c in "_-" for c in item_id):
        raise StoreError(f"not a valid id: {item_id!r}")
    return item_id


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)

    # --- received ----------------------------------------------------------------------
    def add_received(self, message: dict, received_at: float | None = None) -> str:
        received_at = time.time() if received_at is None else received_at
        digest = hashlib.sha256(canonical(message)).hexdigest()[:12]
        item_id = f"msg_{int(received_at)}_{digest}"
        _write(self.root / "received" / f"{item_id}.json",
               {"id": item_id, "received_at": received_at, "read": False, "message": message})
        return item_id

    def received(self, unread_only: bool = False) -> list[dict]:
        items = [_read(p) for p in sorted((self.root / "received").glob("msg_*.json"))]
        return [i for i in items if not (unread_only and i["read"])]

    def read_received(self, item_id: str, mark: bool = True) -> dict:
        path = self.root / "received" / f"{_safe_id(item_id, 'msg_')}.json"
        if not path.is_file():
            raise StoreError(f"no message {item_id}")
        item = _read(path)
        if mark and not item["read"]:
            item["read"] = True
            _write(path, item)
        return item

    # --- sent --------------------------------------------------------------------------
    def add_sent(self, message: dict, status: int, reply: dict | None) -> str:
        item_id = f"out_{int(time.time())}_{secrets.token_hex(3)}"
        _write(self.root / "sent" / f"{item_id}.json",
               {"id": item_id, "sent_at": time.time(), "status": status, "reply": reply, "message": message})
        return item_id

    # --- approvals ---------------------------------------------------------------------
    def request_approval(self, *, principal: str, thread: str, intent: str, body: dict, summary: str,
                         to: str | None = None, topic: str | None = None, agent: str | None = None) -> str:
        item_id = f"apr_{secrets.token_hex(5)}"
        _write(self.root / "approvals" / "pending" / f"{item_id}.json", {
            "id": item_id, "requested_at": time.time(), "agent": agent, "principal": principal,
            "to": to, "topic": topic, "thread": thread, "intent": intent, "body": body,
            "body_sha256": body_digest(body), "summary": summary,
        })
        return item_id

    def pending_approvals(self) -> list[dict]:
        return [_read(p) for p in sorted((self.root / "approvals" / "pending").glob("apr_*.json"))]

    def approval_request(self, item_id: str) -> dict:
        _safe_id(item_id, "apr_")
        for state in ("pending", "signed", "denied"):
            path = self.root / "approvals" / state / f"{item_id}.json"
            if path.is_file():
                return {**_read(path), "state": state}
        raise StoreError(f"no approval request {item_id}")

    def sign_approval(self, item_id: str, principal_key: Ed25519PrivateKey) -> dict:
        request = self.approval_request(item_id)
        if request["state"] != "pending":
            raise StoreError(f"{item_id} is already {request['state']}")
        receipt = issue_approval(principal_key, principal=request["principal"], thread=request["thread"],
                                 intent=request["intent"], body=request["body"], summary=request["summary"])
        request.pop("state")
        _write(self.root / "approvals" / "signed" / f"{item_id}.json", {**request, "receipt": receipt})
        (self.root / "approvals" / "pending" / f"{item_id}.json").unlink()
        return receipt

    def deny_approval(self, item_id: str) -> None:
        request = self.approval_request(item_id)
        if request["state"] != "pending":
            raise StoreError(f"{item_id} is already {request['state']}")
        request.pop("state")
        _write(self.root / "approvals" / "denied" / f"{item_id}.json", {**request, "denied_at": time.time()})
        (self.root / "approvals" / "pending" / f"{item_id}.json").unlink()

    def receipt(self, item_id: str, body: dict) -> dict:
        """The signed receipt for ``item_id``; fails unless it was approved for exactly ``body``."""
        request = self.approval_request(item_id)
        if request["state"] != "signed":
            raise StoreError(f"{item_id} is {request['state']}: the human has not approved it")
        if request["body_sha256"] != body_digest(body):
            raise StoreError(f"{item_id} was approved for a different body")
        return request["receipt"]
