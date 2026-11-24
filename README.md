<p align="center">
  <img src="docs/assets/banner.svg" alt="Elçi: your agent talks to their agent, safely" width="100%">
</p>

<p align="center">
  <a href="https://github.com/ArdaYMC/elci/actions/workflows/test.yml"><img src="https://github.com/ArdaYMC/elci/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/spec-draft%200.0.x-orange" alt="spec draft 0.0.x">
  <a href="https://pypi.org/project/elci/"><img src="https://img.shields.io/pypi/v/elci?color=3776AB" alt="PyPI"></a>
  <a href="https://github.com/ArdaYMC/elci/issues?q=is%3Aopen+label%3A%22good+first+issue%22"><img src="https://img.shields.io/github/issues/ArdaYMC/elci/good%20first%20issue?label=good%20first%20issues&color=7057ff" alt="good first issues"></a>
</p>

# Elçi

**An open protocol for personal AI agents to talk to other people's agents, safely.**

*Elçi* (pronounced "el-chee") is Turkish for *envoy*: someone who speaks on your behalf,
with a clear mandate, and is trusted because of it.

> Status: **draft 0.0.x**. The spec and the reference implementation are being written in the open.
> Expect breaking changes. Feedback and issues are very welcome.

## Why

Personal agents are everywhere, and big players are standardising how *your* agent talks to a
*company* (e.g. Meta & Sierra's Personal Agent Protocol, Decagon's PACT). There is still no open,
widely adopted way for **my agent to talk to your agent**: to schedule a meeting, agree on a
collaboration, or exchange a document, without both of us joining the same closed network.

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
| [`python/`](python/) | Reference implementation ([`pip install elci`](https://pypi.org/project/elci/)). |
| [`examples/`](examples/) | Runnable demo: one person, three agents, need-to-know and email fallback. |
| `typescript/` | Planned SDK (npm). Good first contribution once the vectors stabilise. |

## What works today (0.2.0, spec draft 0.0.6)

- Principal card discovery at `/.well-known/elci.json`, aligned with PAP 1.0 and A2A 1.0 ([mapping](docs/compatibility.md))
- Ed25519-signed messages and delegation tokens (compact JWS) with expiry, agent, topic and intent checks
- A verifying inbox (schema, origin binding, freshness, signature, delegation, replay) and a small HTTP transport
- Need-to-know disclosure levels
- Email fallback for people without an agent, with best-effort reply parsing
- Signed human approval receipts, bound to the exact approved body, required for binding steps
- An MCP server (`elci-mcp`) that sends, reads its inbox and asks you for approvals
- `elci` CLI: init (with local agent discovery), relay, pull, approve, renew, rotate, revoke
- Key lifecycle: key ids, card caching rules, delegation ids and revocation lists
- A free Cloudflare Worker relay template for card hosting and message queueing

Try the demo:

```bash
git clone https://github.com/ArdaYMC/elci && cd elci
pip install -e python && python examples/three_agents.py --yes
```

<p align="center"><img src="docs/assets/demo.svg" alt="Terminal replay of the three-agent demo" width="100%"></p>

<sub>The demo prints in Turkish, the language of its fictional owner. Regenerate this recording with
`python docs/assets/render_demo.py`.</sub>

## Get your Elçi address

```bash
pip install 'elci[mcp]'
elci init --name "Your Name" --domain you.example
```

`elci init` shows the agents it finds on your computer (Claude Code projects and subagents, Claude
Desktop) and makes public only the ones you pick. It creates your keys, signs a delegation for each
agent and writes the card to publish at `https://<domain>/.well-known/elci.json`.

No server or domain? The [Cloudflare relay](templates/cloudflare/) gives you a free
`*.workers.dev` address that serves your card and queues your messages; `elci pull` verifies them on
your machine.

## Use it from Claude Code (MCP)

Connect each public agent once (`elci init` prints the exact commands):

```bash
claude mcp add elci -e ELCI_AGENT=assistant -- elci-mcp
```

Tools: `discover`, `route`, `send_message`, `check_inbox`, `read_message`, `request_approval`,
`approval_status`, `draft_email`, `read_email_reply`, `redact_availability`.

Binding steps need you, not the agent. The agent calls `request_approval`; you review and sign in a
terminal:

```bash
elci approvals          # what your agents are waiting on
elci approve apr_3f9c…  # shows the exact offer, asks "yes", signs with your principal key
```

The MCP server never loads the principal key, so an agent cannot approve on its own.

## Keys: renew, rotate, revoke

```bash
elci status              # delegations and when they expire (90 days by default)
elci renew               # re-issue delegations
elci rotate assistant    # new agent key; the old delegation is revoked
elci rotate --principal  # new principal key; every delegation is re-issued
elci revoke dlg_…        # revoke one delegation
```

Republish the card after each change (`elci relay` does it for the Cloudflare relay). What to do when a
key leaks is in [spec section 7](spec/README.md#7-key-lifecycle).

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
