"""``elci``: set up your Elçi address, receive messages and approve binding steps.

  elci init       create keys, delegations and your public card (offers the agents it finds)
  elci agents     agents found on this computer, and which ones are public
  elci add        make one more agent public;  elci remove  takes one out
  elci card       print the card to publish at https://<domain>/.well-known/elci.json
  elci check      fetch and validate someone's card
  elci serve      run an inbox on this machine (behind your own HTTPS)
  elci relay      connect a Cloudflare Worker relay and publish your card to it
  elci pull       fetch queued messages from the relay and verify them locally
  elci inbox      list received messages
  elci approvals  list approval requests from your agents
  elci approve    review and sign one (needs the principal key)
  elci deny       refuse one
  elci status     delegations, expiry and revocations
  elci renew      re-issue delegations before they expire
  elci rotate     replace an agent key (or --principal) after a leak or on schedule
  elci revoke     revoke one delegation by id
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .discover import Candidate, find_local_agents, slug
from .home import Home, HomeError, default_home
from .inbox import USER_AGENT, CardCache, Inbox, Rejected, fetch_card, is_domain_name, serve
from .store import Store, StoreError


def _out(text: str = "") -> None:
    print(text)


def _passphrase(confirm: bool = False) -> str | None:
    env = os.environ.get("ELCI_PASSPHRASE")
    if env is not None:
        return env or None
    first = getpass.getpass("Principal key passphrase (empty for none): ")
    if confirm and first and getpass.getpass("Repeat it: ") != first:
        raise HomeError("passphrases do not match")
    return first or None


def _ts(value: float | int | None) -> str:
    if value is None:
        return "-"
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _parse_agents(specs: list[str]) -> dict[str, tuple[str, ...]]:
    agents = {}
    for spec in specs:
        name, _, topics = spec.partition(":")
        if not name or not topics or not all(c.isalnum() or c in "-_" for c in name):
            raise HomeError(f"--agent wants name:topic[,topic], got {spec!r}")
        agents[name] = tuple(t.strip() for t in topics.split(",") if t.strip())
    return agents


# --- commands ---------------------------------------------------------------------------------

def _pick_local_agents(candidates: list[Candidate]) -> tuple[dict[str, tuple[str, ...]], dict[str, dict]]:
    """Show the agents found on this computer; the user picks which ones others may reach."""
    if not candidates:
        _out("No agents found on this computer. Add one with --agent name:topics.")
        return {}, {}
    _out("Agents found on this computer. Nothing is public until you pick it:")
    for i, c in enumerate(candidates, 1):
        _out(f"  {i:>2}. {c.name:<24} {c.kind:<22} {c.description}")
    raw = input("Which ones may other people's agents reach? Numbers, comma separated (empty = none): ")
    agents, local = {}, {}
    for part in filter(None, (x.strip() for x in raw.split(","))):
        if not part.isdigit() or not 1 <= int(part) <= len(candidates):
            raise HomeError(f"not in the list: {part}")
        c = candidates[int(part) - 1]
        name = slug(input(f"  public name for {c.name} [{c.name}]: ").strip() or c.name)
        topics = input(f"  topics {name} handles, comma separated [collaboration]: ").strip() or "collaboration"
        agents[name] = tuple(t.strip() for t in topics.split(",") if t.strip())
        local[name] = {"kind": c.kind, "path": c.path, "source": c.name}
    return agents, local


def _mcp_lines(config: dict) -> list[str]:
    lines = []
    for name, a in config["agents"].items():
        loc = a.get("local") or {}
        cand = Candidate(name, loc.get("kind", "manual"), "", loc.get("path"))
        lines.append(f"  {name}: {cand.mcp_command}")
    return lines


def cmd_agents(args, home: Home) -> int:
    exposed = home.config()["agents"] if home.exists() else {}
    sources = {(a.get("local") or {}).get("source") for a in exposed.values()}
    candidates = find_local_agents()
    if not candidates:
        _out("No local agents found.")
    for c in candidates:
        mark = "public" if c.name in sources else "private"
        _out(f"  {c.name:<24} {c.kind:<22} {mark:<8} {c.description}")
    return 0


def cmd_add(args, home: Home) -> int:
    agents = _parse_agents([args.agent])
    (name, topics), = agents.items()
    home.add_agent(name, topics, _passphrase(), days=args.days)
    _out(f"✓ added {name}. Connect it: claude mcp add elci -e ELCI_AGENT={name} -- elci-mcp")
    _republish_hint(home)
    return 0


def cmd_remove(args, home: Home) -> int:
    home.remove_agent(args.name)
    _out(f"✓ {args.name} is out of the card and its delegation is revoked.")
    _republish_hint(home)
    return 0


def cmd_init(args, home: Home) -> int:
    fallback = f"mailto:{args.email}" if args.email else None
    agents, local = _parse_agents(args.agent), {}
    if not agents:
        agents, local = _pick_local_agents(find_local_agents())
    config = home.init(name=args.name, domain=args.domain, agents=agents, local=local,
                       passphrase=_passphrase(confirm=True), fallback=fallback, days=args.days)
    domain = config["principal"]["domain"]
    _out(f"Created your Elçi home in {home.path}")
    for name, a in config["agents"].items():
        _out(f"  agent {name}: {a['id']}  topics: {', '.join(a['topics'])}")
    _out("")
    _out("Connect each agent to Elçi (run once):")
    for line in _mcp_lines(config):
        _out(line)
    _out("")
    _out("Next:")
    _out(f"  1. Publish {home.card_path} at https://{domain}/.well-known/elci.json")
    _out("     No server? `elci relay --help` sets up a free Cloudflare Worker that serves the card")
    _out("     and queues your messages (templates/cloudflare in the repository).")
    _out("  2. Receive: `elci serve` behind your HTTPS, or `elci pull` from the relay.")
    _out("Keep principal.pem off shared machines: it is what approves binding steps.")
    return 0


def cmd_card(args, home: Home) -> int:
    _out(home.card_path.read_text(encoding="utf-8").rstrip())
    return 0


def cmd_check(args, home: Home) -> int:
    domain = args.domain.lower()
    if not is_domain_name(domain):
        _out(f"✗ {domain!r} is not a plain DNS name")
        return 1
    try:
        card = fetch_card(domain)
    except Exception as exc:  # noqa: BLE001 - report any failure to the user
        _out(f"✗ could not load https://{domain}/.well-known/elci.json: {exc}")
        return 1
    problems = []
    if card.domain.lower() != domain:
        problems.append(f"card says domain {card.domain!r}, served from {domain!r}")
    if not card.principal_keys:
        problems.append("no principal.jwks: nobody can verify this principal's delegations")
    keysets = [("principal", card.principal_keys)] + [(a.id, a.keys) for a in card.agents]
    for owner, keys in keysets:
        kids = [k.get("kid") for k in keys]
        if len(keys) > 1 and (None in kids or len(set(kids)) != len(kids)):
            problems.append(f"{owner}: several keys need unique kids (spec section 7)")
    for a in card.agents:
        host = a.id.split("/")[2].lower()
        if host != domain and not host.endswith("." + domain):
            problems.append(f"agent {a.id} is not on {domain}")
    _out(f"{card.principal} ({card.domain})")
    for a in card.agents:
        _out(f"  {a.name or a.id}: {', '.join(a.topics)} -> {a.endpoint}")
    if card.fallback:
        _out(f"  fallback: {card.fallback}")
    if card.revoked:
        _out(f"  revoked delegations: {len(card.revoked)}")
    for p in problems:
        _out(f"✗ {p}")
    if not problems:
        _out("✓ card is valid")
    return 1 if problems else 0


def _inbox(home: Home) -> Inbox:
    return Inbox(home.card(), resolve_card=CardCache())


def cmd_serve(args, home: Home) -> int:
    store, inbox = Store(home.store_path), _inbox(home)

    def handle(message: dict) -> dict:
        return {"stored": store.add_received(message)}

    server = serve(inbox, handle, host=args.host, port=args.port)
    host, port = server.server_address[:2]
    _out(f"Elçi inbox on http://{host}:{port}/ (put it behind HTTPS at your card's endpoints). Ctrl+C stops.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


def _relay(home: Home) -> dict:
    relay = home.config().get("relay")
    if not relay:
        raise HomeError("no relay yet: run `elci relay` first")
    return relay


def _relay_call(relay: dict, method: str, path: str, payload: object | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"https://{relay['domain']}{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {relay['token']}",
                                          "Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - https only
        body = resp.read()
    return json.loads(body) if body else None


def cmd_relay(args, home: Home) -> int:
    config = home.config()
    domain = config["principal"]["domain"]
    if args.token:
        token = args.token
    elif (config.get("relay") or {}).get("token"):
        token = config["relay"]["token"]
    else:
        import secrets

        token = secrets.token_urlsafe(32)
    config["relay"] = {"domain": domain, "token": token}
    home.save_config(config)
    if args.show_token:
        _out("Set this as the Worker secret (npx wrangler secret put ELCI_TOKEN):")
        _out(token)
        return 0
    try:
        _relay_call(config["relay"], "PUT", "/admin/card", json.loads(home.card_path.read_text("utf-8")))
    except Exception as exc:  # noqa: BLE001
        _out(f"✗ could not publish the card to https://{domain}: {exc}")
        _out("  Deployed the Worker and set ELCI_TOKEN? `elci relay --show-token` prints the token.")
        return 1
    _out(f"✓ card published at https://{domain}/.well-known/elci.json")
    return 0


def cmd_pull(args, home: Home) -> int:
    relay, store, inbox = _relay(home), Store(home.store_path), _inbox(home)
    queued = _relay_call(relay, "GET", "/admin/messages") or []
    done, kept = [], 0
    for item in queued:
        try:
            inbox.accept(item["message"], received_at=item["received_at"] / 1000)
            store.add_received(item["message"], item["received_at"] / 1000)
            kept += 1
        except Rejected as exc:
            _out(f"  dropped {item['id']}: {exc}")
        done.append(item["id"])
    if done:
        _relay_call(relay, "POST", "/admin/ack", {"ids": done})
    _out(f"{kept} new message(s), {len(done) - kept} rejected")
    return 0


def cmd_inbox(args, home: Home) -> int:
    items = Store(home.store_path).received(unread_only=not args.all)
    if not items:
        _out("No messages." if args.all else "No unread messages.")
    for i in items:
        m = i["message"]
        _out(f"{i['id']}  {_ts(i['received_at'])}  {m['on_behalf_of']}  {m['intent']} / {m['topic']}  "
             f"{'' if i['read'] else '(new)'}")
    return 0


def _show_request(r: dict) -> None:
    _out(f"{r['id']}  {r['intent'].upper()}  thread {r['thread']}")
    _out(f"  summary: {r['summary']}")
    if r.get("to"):
        _out(f"  to:      {r['to']}")
    _out(f"  body:    {json.dumps(r['body'], ensure_ascii=False)}")
    if r.get("agent"):
        _out(f"  asked by {r['agent']} at {_ts(r['requested_at'])}")


def cmd_approvals(args, home: Home) -> int:
    pending = Store(home.store_path).pending_approvals()
    if not pending:
        _out("Nothing waiting for your approval.")
    for r in pending:
        _show_request(r)
    return 0


def cmd_approve(args, home: Home) -> int:
    store = Store(home.store_path)
    request = store.approval_request(args.id)
    if request["state"] != "pending":
        raise StoreError(f"{args.id} is already {request['state']}")
    _show_request(request)
    if not args.yes and input("Approve exactly this? Type 'yes': ").strip().lower() != "yes":
        _out("Not approved.")
        return 1
    store.sign_approval(args.id, home.principal_key(_passphrase()))
    _out(f"✓ signed. Your agent can now send it with approval_id={args.id}")
    return 0


def cmd_deny(args, home: Home) -> int:
    Store(home.store_path).deny_approval(args.id)
    _out(f"Denied {args.id}.")
    return 0


def cmd_status(args, home: Home) -> int:
    config = home.config()
    _out(f"{config['principal']['name']} ({config['principal']['domain']})  home: {home.path}")
    soon = time.time() + 14 * 86400
    for d in home.delegations():
        warn = "  ← renew soon (`elci renew`)" if (d["expires_at"] or 0) < soon else ""
        _out(f"  {d['agent']}: delegation {d['jti']} expires {_ts(d['expires_at'])}{warn}")
    if config["principal"].get("revoked"):
        _out(f"  revoked: {', '.join(config['principal']['revoked'])}")
    _out(f"  relay: {config['relay']['domain'] if config.get('relay') else 'none'}")
    return 0


def _republish_hint(home: Home) -> None:
    if home.config().get("relay"):
        _out("Run `elci relay` to publish the updated card.")
    else:
        _out(f"Publish the updated {home.card_path} again.")


def cmd_renew(args, home: Home) -> int:
    names = home.renew(_passphrase(), days=args.days)
    _out(f"✓ renewed delegations for {', '.join(names)}")
    _republish_hint(home)
    return 0


def cmd_rotate(args, home: Home) -> int:
    if args.principal:
        kid = home.rotate_principal(_passphrase(), days=args.days)
        _out(f"✓ new principal key {kid}; every delegation was re-issued.")
    else:
        if not args.agent:
            raise HomeError("name the agent (`elci rotate assistant`) or pass --principal")
        kid = home.rotate_agent(args.agent, _passphrase(), days=args.days)
        _out(f"✓ new key {kid} for {args.agent}; its old delegation is revoked.")
    _republish_hint(home)
    return 0


def cmd_revoke(args, home: Home) -> int:
    home.revoke(args.jti)
    _out(f"✓ {args.jti} added to the card's revocation list.")
    _republish_hint(home)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elci", description="Your Elçi address, inbox and approvals.")
    parser.add_argument("--home", help=f"Elçi home folder (default {default_home()}, or $ELCI_HOME)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create keys, delegations and your card")
    p.add_argument("--name", required=True, help="your name as others should see it")
    p.add_argument("--domain", required=True, help="where your card lives, e.g. arda.example or x.workers.dev")
    p.add_argument("--agent", action="append", default=[], metavar="NAME:TOPICS",
                   help="a public agent and its topics, e.g. assistant:scheduling,collaboration (repeatable);"
                        " without it, init shows the agents it finds and lets you pick")
    p.add_argument("--email", help="fallback address for people without an agent")
    p.add_argument("--days", type=int, default=90, help="delegation lifetime in days (default 90)")
    p.set_defaults(fn=cmd_init)

    sub.add_parser("agents", help="agents found on this computer").set_defaults(fn=cmd_agents)
    p = sub.add_parser("add", help="make one more agent public")
    p.add_argument("agent", metavar="NAME:TOPICS")
    p.add_argument("--days", type=int, default=90)
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("remove", help="take an agent out of the card and revoke it")
    p.add_argument("name")
    p.set_defaults(fn=cmd_remove)
    sub.add_parser("card", help="print your public card").set_defaults(fn=cmd_card)
    p = sub.add_parser("check", help="fetch and validate someone's card")
    p.add_argument("domain")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("serve", help="run an inbox on this machine")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("relay", help="use a Cloudflare Worker relay at your domain and publish your card to it")
    p.add_argument("--token", help="use this relay token instead of generating one")
    p.add_argument("--show-token", action="store_true", help="print the token to set as ELCI_TOKEN and stop")
    p.set_defaults(fn=cmd_relay)
    sub.add_parser("pull", help="fetch and verify queued messages from the relay").set_defaults(fn=cmd_pull)
    p = sub.add_parser("inbox", help="list received messages")
    p.add_argument("--all", action="store_true", help="include read messages")
    p.set_defaults(fn=cmd_inbox)
    sub.add_parser("approvals", help="list pending approval requests").set_defaults(fn=cmd_approvals)
    p = sub.add_parser("approve", help="review and sign an approval request")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt (scripts only)")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("deny", help="refuse an approval request")
    p.add_argument("id")
    p.set_defaults(fn=cmd_deny)
    sub.add_parser("status", help="delegations, expiry and revocations").set_defaults(fn=cmd_status)
    p = sub.add_parser("renew", help="re-issue delegations")
    p.add_argument("--days", type=int, default=90)
    p.set_defaults(fn=cmd_renew)
    p = sub.add_parser("rotate", help="replace an agent key, or the principal key with --principal")
    p.add_argument("agent", nargs="?")
    p.add_argument("--principal", action="store_true")
    p.add_argument("--days", type=int, default=90)
    p.set_defaults(fn=cmd_rotate)
    p = sub.add_parser("revoke", help="revoke a delegation by its id (see `elci status`)")
    p.add_argument("jti")
    p.set_defaults(fn=cmd_revoke)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Home(Path(args.home) if args.home else default_home())
    try:
        return args.fn(args, home)
    except (HomeError, StoreError) as exc:
        print(f"elci: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
