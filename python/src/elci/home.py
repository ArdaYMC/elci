"""Your Elçi home: keys, delegations and the public card, kept in one folder (``~/.elci``).

Layout::

    config.json        principal, agents, delegations, relay settings (private, 0600)
    principal.pem      principal key, encrypted with your passphrase when you set one (0600)
    agents/<name>.pem  one key per agent (0600)
    card.json          your public card: publish it at https://<domain>/.well-known/elci.json
    store/             received and sent messages, approval requests and receipts

The principal key signs delegations and approval receipts. Agents (and the MCP server) never load
it: they only read their own key and delegation, so an agent cannot approve on your behalf.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .agent import Agent
from .card import AgentCard
from .crypto import Delegation, b64u, delegation_claims, issue_delegation, public_jwk
from .inbox import is_domain_name

DEFAULT_DAYS = 90
DEFAULT_INTENTS = ("propose", "query", "answer", "decline", "needs_human", "accept")


def _intents(intents) -> list[str]:
    if not intents:
        return list(DEFAULT_INTENTS)
    unknown = set(intents) - set(DEFAULT_INTENTS)
    if unknown:
        raise HomeError(f"unknown intents: {', '.join(sorted(unknown))}; use {', '.join(DEFAULT_INTENTS)}")
    return [i for i in DEFAULT_INTENTS if i in intents]


def default_home() -> Path:
    return Path(os.environ.get("ELCI_HOME") or Path.home() / ".elci")


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _new_kid(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(2)}"


def _pem(key: Ed25519PrivateKey, passphrase: str | None) -> bytes:
    enc = (serialization.BestAvailableEncryption(passphrase.encode("utf-8")) if passphrase
           else serialization.NoEncryption())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)


def _load_pem(path: Path, passphrase: str | None) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(),
                                                 passphrase.encode("utf-8") if passphrase else None)
    except TypeError as exc:  # encrypted key but no passphrase, or the other way round
        raise HomeError("the principal key is protected: type its passphrase when asked "
                        "(or set ELCI_PASSPHRASE)") from exc
    except ValueError as exc:
        raise HomeError("wrong passphrase for the principal key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise HomeError(f"{path} is not an Ed25519 key")
    return key


class HomeError(RuntimeError):
    """The Elçi home is missing, incomplete or locked."""


@dataclass
class Home:
    path: Path

    # --- files --------------------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.path / "config.json"

    @property
    def card_path(self) -> Path:
        return self.path / "card.json"

    @property
    def store_path(self) -> Path:
        return self.path / "store"

    def exists(self) -> bool:
        return self.config_path.is_file()

    def config(self) -> dict:
        if not self.exists():
            raise HomeError(f"no Elçi home at {self.path}; run `elci init` first")
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def save_config(self, config: dict) -> None:
        _write_private(self.config_path, json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8"))

    # --- keys ---------------------------------------------------------------------------
    def principal_key(self, passphrase: str | None = None) -> Ed25519PrivateKey:
        if passphrase is None:
            passphrase = os.environ.get("ELCI_PASSPHRASE") or None
        return _load_pem(self.path / "principal.pem", passphrase)

    def agent_key(self, name: str) -> Ed25519PrivateKey:
        return _load_pem(self.path / "agents" / f"{name}.pem", None)

    def agent(self, name: str | None = None) -> Agent:
        """An Agent ready to sign messages. Loads only that agent's key and delegation."""
        config = self.config()
        agents = config["agents"]
        if name is None:
            if len(agents) != 1:
                raise HomeError(f"several agents here, pick one: {', '.join(agents)}")
            name = next(iter(agents))
        if name not in agents:
            raise HomeError(f"no agent named {name!r}; have {', '.join(agents)}")
        entry = agents[name]
        return Agent(entry["id"], config["principal"]["domain"], self.agent_key(name), entry["delegation"])

    # --- card ---------------------------------------------------------------------------
    def build_card(self, config: dict | None = None) -> dict:
        config = config or self.config()
        p = config["principal"]
        principal = {"name": p["name"], "domain": p["domain"], "jwks": {"keys": p["keys"]}}
        if p.get("fallback"):
            principal["fallback"] = p["fallback"]
        if p.get("revoked"):
            principal["revoked"] = p["revoked"]
        agents = [{"id": a["id"], "name": n, "topics": a["topics"], "endpoint": a["endpoint"],
                   "jwks": {"keys": a["keys"]}} for n, a in config["agents"].items()]
        card = {"protocol_version": "0.0.2", "principal": principal, "agents": agents}
        AgentCard.from_dict(card)  # schema check
        return card

    def card(self) -> AgentCard:
        return AgentCard.from_dict(json.loads(self.card_path.read_text(encoding="utf-8")))

    def _save(self, config: dict) -> None:
        self.save_config(config)
        self.card_path.write_text(json.dumps(self.build_card(config), indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")

    # --- lifecycle ----------------------------------------------------------------------
    def init(self, *, name: str, domain: str, agents: dict[str, tuple[str, ...]],
             passphrase: str | None, fallback: str | None = None, days: int = DEFAULT_DAYS,
             local: dict[str, dict] | None = None) -> dict:
        """Create keys, delegations and the card. ``agents`` maps agent name to topics.

        ``local`` optionally records, per agent, which local agent speaks for it (kind, path).
        """
        if self.exists():
            raise HomeError(f"{self.path} already has an Elçi home")
        domain = domain.lower()
        if not is_domain_name(domain):
            raise HomeError(f"{domain!r} is not a DNS name (like arda.example or x.workers.dev)")
        if not agents:
            raise HomeError("add at least one agent, e.g. --agent assistant:scheduling")
        principal_key = Ed25519PrivateKey.generate()
        kid = _new_kid("principal")
        _write_private(self.path / "principal.pem", _pem(principal_key, passphrase))
        config = {
            "principal": {"name": name, "domain": domain, "fallback": fallback,
                          "keys": [public_jwk(principal_key.public_key(), kid)], "kid": kid, "revoked": []},
            "agents": {},
            "relay": None,
        }
        for agent_name, topics in agents.items():
            self._add(config, agent_name, topics, principal_key, days, (local or {}).get(agent_name))
        self._save(config)
        return config

    def _add(self, config: dict, name: str, topics, principal_key, days: int, local: dict | None,
             intents=None) -> None:
        if not name or not all(c.isalnum() or c in "-_" for c in name):
            raise HomeError(f"agent names use letters, digits, - and _: {name!r}")
        if not topics:
            raise HomeError(f"give {name} at least one topic")
        domain = config["principal"]["domain"]
        config["agents"][name] = {
            "id": f"https://{domain}/agents/{name}",
            "endpoint": f"https://{domain}/inbox/{name}",
            "topics": list(topics),
            "intents": _intents(intents),
            "local": local,
        }
        self._new_agent_key(config, name)
        self._delegate(config, name, principal_key, days)

    def add_agent(self, name: str, topics, passphrase: str | None = None, days: int = DEFAULT_DAYS,
                  local: dict | None = None, intents=None) -> dict:
        """``intents`` narrows what the agent may send; leave out ``accept`` for an agent that must
        never commit to anything (a public demo, say)."""
        config = self.config()
        if name in config["agents"]:
            raise HomeError(f"{name} already exists")
        self._add(config, name, topics, self.principal_key(passphrase), days, local, intents)
        self._save(config)
        return config["agents"][name]

    def export_agent(self, name: str) -> dict:
        """What a hosted agent needs to sign as ``name``: id, endpoint, delegation and its private key.

        This is the agent key, never the principal key. Renewing or rotating changes it; export again.
        """
        config = self.config()
        if name not in config["agents"]:
            raise HomeError(f"no agent named {name!r}")
        entry = config["agents"][name]
        raw = self.agent_key(name).private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                 serialization.NoEncryption())
        jwk = {**entry["keys"][0], "d": b64u(raw)}
        return {"id": entry["id"], "endpoint": entry["endpoint"], "domain": config["principal"]["domain"],
                "topics": entry["topics"], "intents": entry["intents"], "delegation": entry["delegation"],
                "jwk": jwk}

    def remove_agent(self, name: str) -> None:
        """Take an agent out of the card and revoke its delegation."""
        config = self.config()
        entry = config["agents"].pop(name, None)
        if entry is None:
            raise HomeError(f"no agent named {name!r}")
        jti = delegation_claims(entry["delegation"]).get("jti")
        if jti:
            config["principal"]["revoked"] = sorted(set(config["principal"]["revoked"]) | {jti})
        (self.path / "agents" / f"{name}.pem").unlink(missing_ok=True)
        self._save(config)

    def _new_agent_key(self, config: dict, name: str) -> None:
        key = Ed25519PrivateKey.generate()
        _write_private(self.path / "agents" / f"{name}.pem", _pem(key, None))
        config["agents"][name]["keys"] = [public_jwk(key.public_key(), _new_kid(name))]

    def _delegate(self, config: dict, name: str, principal_key: Ed25519PrivateKey, days: int) -> None:
        entry = config["agents"][name]
        token = issue_delegation(
            Delegation(config["principal"]["domain"], entry["id"], tuple(entry["topics"]),
                       tuple(entry["intents"]), int(time.time()) + days * 86400),
            principal_key, kid=config["principal"]["kid"])
        entry["delegation"] = token

    def renew(self, passphrase: str | None = None, days: int = DEFAULT_DAYS) -> list[str]:
        """Re-issue every agent's delegation (same keys)."""
        config, key = self.config(), self.principal_key(passphrase)
        for name in config["agents"]:
            self._delegate(config, name, key, days)
        self._save(config)
        return list(config["agents"])

    def rotate_agent(self, name: str, passphrase: str | None = None, days: int = DEFAULT_DAYS) -> str:
        """New key and delegation for one agent; the old delegation is revoked."""
        config = self.config()
        if name not in config["agents"]:
            raise HomeError(f"no agent named {name!r}")
        key = self.principal_key(passphrase)
        old = delegation_claims(config["agents"][name]["delegation"]).get("jti")
        self._new_agent_key(config, name)
        self._delegate(config, name, key, days)
        if old:
            config["principal"]["revoked"] = sorted(set(config["principal"]["revoked"]) | {old})
        self._save(config)
        return config["agents"][name]["keys"][0]["kid"]

    def rotate_principal(self, passphrase: str | None = None, new_passphrase: str | None = None,
                         days: int = DEFAULT_DAYS) -> str:
        """Replace the principal key and re-issue every delegation with it."""
        config = self.config()
        self.principal_key(passphrase)  # prove you hold the current one
        key = Ed25519PrivateKey.generate()
        kid = _new_kid("principal")
        _write_private(self.path / "principal.pem", _pem(key, new_passphrase if new_passphrase is not None
                                                          else passphrase or os.environ.get("ELCI_PASSPHRASE")))
        config["principal"].update(keys=[public_jwk(key.public_key(), kid)], kid=kid, revoked=[])
        for name in config["agents"]:
            self._delegate(config, name, key, days)
        self._save(config)
        return kid

    def revoke(self, jti: str) -> None:
        config = self.config()
        config["principal"]["revoked"] = sorted(set(config["principal"]["revoked"]) | {jti})
        self._save(config)

    def delegations(self) -> list[dict]:
        out = []
        for name, entry in self.config()["agents"].items():
            claims = delegation_claims(entry["delegation"])
            out.append({"agent": name, "jti": claims.get("jti"), "expires_at": claims.get("exp"),
                        "topics": claims.get("topics"), "intents": claims.get("intents")})
        return out
