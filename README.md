# Elçi

**An open protocol for personal AI agents to talk to other people's agents — safely.**

*Elçi* (pronounced "el-chee") is Turkish for *envoy*: someone who speaks on your behalf,
with a clear mandate, and is trusted because of it.

> Status: **draft 0.0.x** — the spec and the reference implementation are being written in the open.
> Expect breaking changes. Feedback and issues are very welcome.

## Why

Personal agents are everywhere, and big players are standardising how *your* agent talks to a
*company* (e.g. Meta & Sierra's Personal Agent Protocol, Decagon's PACT). There is still no open,
widely adopted way for **my agent to talk to your agent** — to schedule a meeting, agree on a
collaboration, or exchange a document — without both of us joining the same closed network.

Elçi focuses on three things existing attempts leave out:

1. **Compatible, not competing.** Discovery and authorization reuse the patterns of the
   company-facing protocols (`/.well-known/` documents, OAuth-style delegation), extended to
   person-to-person.
2. **Need-to-know between agents.** One person often has several agents (personal, work,
   creator). Each one may disclose only what its mandate allows. Asking "is Arda free on
   Thursday at 14:00?" returns *busy*, never *why*.
3. **Works when the other side has no agent.** If no agent card is found, Elçi falls back to a
   plain, human-readable email and parses the reply.

## Repository layout

| Path | What |
| --- | --- |
| [`spec/`](spec/) | The protocol draft, JSON Schemas and language-neutral conformance vectors. **This is the standard.** |
| [`python/`](python/) | Reference implementation (PyPI package `elci`). |
| [`examples/`](examples/) | Runnable demo: one person, three agents, need-to-know and email fallback. |
| `typescript/` | Planned SDK (npm). Good first contribution once the vectors stabilise. |

## What works today (0.0.4)

- Principal card discovery at `/.well-known/elci.json`, aligned with PAP 1.0 and A2A 1.0 ([mapping](docs/compatibility.md))
- Ed25519-signed messages and delegation tokens (compact JWS) with expiry, agent, topic and intent checks
- A verifying inbox (schema, signature, delegation, replay) and a small HTTP transport
- Need-to-know disclosure levels
- Email fallback for people without an agent, with best-effort reply parsing
- Signed human approval receipts required for binding steps
- An MCP server (`elci-mcp`) so Claude Code or any MCP host can use Elçi

Try the demo: `pip install -e python && python examples/three_agents.py --yes`

## Use it from Claude Code (MCP)

```bash
pip install 'elci[mcp]'
claude mcp add elci -- elci-mcp
```

Tools: `discover`, `route`, `send_message`, `draft_email`, `read_email_reply`, `redact_availability`.
Sending needs `ELCI_AGENT_ID`, `ELCI_PRINCIPAL_DOMAIN`, `ELCI_AGENT_KEY_HEX` and `ELCI_DELEGATION`
in the environment; keep the key in a secret store. `accept` is refused without a signed approval receipt.

## Quick look

```python
from elci import AgentCard, DisclosurePolicy

card = AgentCard.from_dict({...})          # fetched from https://example.com/.well-known/elci.json
policy = DisclosurePolicy(allowed={"availability": "busy_free"})
policy.redact({"slot": "2026-11-26T14:00", "busy": True, "reason": "supplier meeting"})
# -> {"slot": "2026-11-26T14:00", "busy": True}
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). AI-assisted contributions are welcome when a human
has read, understood and tested them, and the PR says so in one line.

## License

[MIT](LICENSE)
