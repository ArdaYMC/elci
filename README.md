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
| `typescript/` | Planned SDK (npm). Good first contribution once the vectors stabilise. |

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
