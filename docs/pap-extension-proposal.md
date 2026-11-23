# Draft: person-to-person extension for the Personal Agent Protocol

Status: **draft for Arda's review — not posted anywhere yet.** Intended as a GitHub issue / discussion
on the PAP repository once Arda approves the wording.

---

**Title:** Proposal: a person-to-person profile (principal cards, need-to-know disclosure, email fallback)

PAP 1.0 standardises how a personal agent talks to a *company*: the company publishes
`/.well-known/poppy.json`, the agent authenticates with OAuth and DPoP. A growing number of
interactions are between two *people*, each with their own agent: scheduling, collaborations,
introductions. Today every project invents its own network for this.

[Elçi](https://github.com/ArdaYMC/elci) is an MIT-licensed experiment in doing that with PAP's
conventions instead of a new stack. We would like feedback on whether it could live as a PAP
extension (`extensions` in `poppy.json`) rather than a separate document.

What it adds:

1. **Principal card** at `/.well-known/elci.json` with the same shape as PAP where possible
   (`protocol_version`, `{name, domain}`, JWK Sets), listing a person's *public* agents by topic.
2. **Delegation tokens** (compact JWS, EdDSA) so a receiver can check that an agent speaks for a
   person, for which topics and intents, until when.
3. **Human approval receipts** for binding steps, signed by the person's key, so the other side
   can verify that a human said yes.
4. **Need-to-know disclosure levels** for one person's several agents (e.g. availability:
   `none` < `busy_free` < `title` < `full`).
5. **Email fallback** with a machine-readable thread footer when the other person has no agent.

Questions for the working group:

- Is a person-to-person profile in scope for PAP, as an extension or a future version?
- Would PAP prefer persons to publish `poppy.json` with a new `person` object instead of a separate file?
- Is there interest in shared conformance vectors for EdDSA signatures and delegation claims?

A runnable demo (one person, three agents, a brand agent over HTTP and a supplier by email) is in
`examples/three_agents.py`.
