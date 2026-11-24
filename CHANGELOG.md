# Changelog

## 0.3.0 (unreleased)

- Public demo agent in the Cloudflare Worker (`ELCI_DEMO`): answers at once with a signed message
  built from fixed sample data, stores nothing, never accepts, rate limited
- `elci add --intents` narrows what an agent may send; `elci export-agent` prints one agent's key
  and delegation for a hosted agent
- `send_message` verifies an answer that comes back in the HTTP response (signature, delegation,
  freshness, sender) and files it in the inbox; unverified answers are flagged, not trusted
- `send_message` refuses, before sending, a topic or intent the agent's own delegation does not
  cover (the receiver would reject it anyway)
- Clearer error when the principal passphrase is left empty at the prompt

## 0.2.1

- Send an `elci/<version>` User-Agent on every outgoing request (card fetch, message send, relay
  calls). Cloudflare refused the default `Python-urllib` agent with 403, so 0.2.0 could not publish
  a card to or pull from the Cloudflare relay.

## 0.2.0

Spec draft 0.0.6.

- Key lifecycle (spec section 7): unique `kid`s, card caching rules with one refetch on a failed
  signature, delegation `jti` and `principal.revoked`, a compromise table
- `elci` CLI: `init` (shows local Claude Code projects, subagents and Claude Desktop; exposes only
  what you pick), `agents`, `add`, `remove`, `card`, `check`, `serve`, `relay`, `pull`, `inbox`,
  `approvals`, `approve`, `deny`, `status`, `renew`, `rotate`, `revoke`
- Principal key in a passphrase-encrypted PEM, never loaded by agents or the MCP server
- `elci-mcp`: `check_inbox`, `read_message`, `request_approval`, `approval_status`; `send_message`
  takes an `approval_id` instead of a raw receipt; config from `elci init`
- Local store for received and sent messages and approval requests
- `templates/cloudflare`: Worker relay (card hosting, queued inbox, token-protected pull)
- `Inbox.accept(received_at=...)` and `CardCache`

## 0.1.0 (first PyPI release)

Spec draft 0.0.5. First release of the `elci` Python package.

- Principal cards at `/.well-known/elci.json`, aligned with PAP 1.0 and A2A 1.0
- Ed25519-signed messages over canonical JSON, compact-JWS delegation tokens
- Verifying inbox: origin binding, 5-minute freshness window, signature, delegation,
  body-bound human approval receipts for binding intents, replay protection
- Need-to-know disclosure levels (`none` < `busy_free` < `title` < `full`)
- Email fallback for people without an agent, with best-effort reply parsing
- `elci-mcp`: MCP server for Claude Code and other MCP hosts (`pip install 'elci[mcp]'`)
- Security review fixes (#13) and conformance vectors in `spec/vectors/`
