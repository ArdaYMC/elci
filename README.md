<p align="center">
  <img src="docs/assets/banner.svg" alt="Elçi: your agent talks to their agent, safely" width="100%">
</p>

<p align="center">
  <a href="https://github.com/ArdaYMC/elci/actions/workflows/test.yml"><img src="https://github.com/ArdaYMC/elci/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/spec-draft%200.0.x-orange" alt="spec draft 0.0.x">
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python 3.10+">
  <a href="https://github.com/ArdaYMC/elci/issues?q=is%3Aopen+label%3A%22good+first+issue%22"><img src="https://img.shields.io/github/issues/ArdaYMC/elci/good%20first%20issue?label=good%20first%20issues&color=7057ff" alt="good first issues"></a>
</p>

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

## How it works

One person, several agents. Only the public ones are listed in the person's card; the private
coordinator that holds everything never talks to the outside world.

<p align="center"><img src="docs/assets/architecture.svg" alt="Architecture: Arda's private coordinator Jarvy feeds two public agents, devbyarda and acme-work; devbyarda talks to a brand's agent over signed HTTPS, acme-work reaches a supplier without an agent by email" width="100%"></p>

A typical exchange: the other side proposes, your agent answers at the level its mandate allows,
and nothing binding happens until you say yes, in a way the other side can verify.

<p align="center"><img src="docs/assets/flow.svg" alt="Message flow: propose, availability lookup, redaction to busy/free, answer, human approval, accept with a signed receipt" width="100%"></p>

## Repository layout

| Path | What |
| --- | --- |
| [`spec/`](spec/) | The protocol draft, JSON Schemas and language-neutral conformance vectors. **This is the standard.** |
| [`python/`](python/) | Reference implementation (Python package `elci`; PyPI release coming soon). |
| [`examples/`](examples/) | Runnable demo: one person, three agents, need-to-know and email fallback. |
| `typescript/` | Planned SDK (npm). Good first contribution once the vectors stabilise. |

## What works today (draft 0.0.5)

- Principal card discovery at `/.well-known/elci.json`, aligned with PAP 1.0 and A2A 1.0 ([mapping](docs/compatibility.md))
- Ed25519-signed messages and delegation tokens (compact JWS) with expiry, agent, topic and intent checks
- A verifying inbox (schema, origin binding, freshness, signature, delegation, replay) and a small HTTP transport
- Need-to-know disclosure levels
- Email fallback for people without an agent, with best-effort reply parsing
- Signed human approval receipts, bound to the exact approved body, required for binding steps
- An MCP server (`elci-mcp`) so Claude Code or any MCP host can use Elçi

Try the demo:

```bash
git clone https://github.com/ArdaYMC/elci && cd elci
pip install -e python && python examples/three_agents.py --yes
```

<p align="center"><img src="docs/assets/demo.svg" alt="Terminal replay of the three-agent demo" width="100%"></p>

<sub>The demo prints in Turkish, the language of its fictional owner. Regenerate this recording with
`python docs/assets/render_demo.py`.</sub>

## Use it from Claude Code (MCP)

```bash
pip install 'elci[mcp] @ git+https://github.com/ArdaYMC/elci#subdirectory=python'
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

## Security

Report vulnerabilities privately, see [SECURITY.md](SECURITY.md). The bundled HTTP server is for local
development and demos; put production endpoints behind HTTPS. Card and key fetches refuse IP literals
and redirects, but DNS can still point a name at an internal address, so run receivers with egress
filtering if they sit next to internal services.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). AI-assisted contributions are welcome when a human
has read, understood and tested them, and the PR says so in one line.

## License

[MIT](LICENSE)
