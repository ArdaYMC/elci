# Compatibility with PAP and A2A

Elçi does not replace the company-facing protocols; it adds the person-to-person case and borrows
their conventions so the same agent can speak all of them.

Sources read on 2026-11-23: [Personal Agent Protocol 1.0](https://personalagentprotocol.org/docs/1.0/spec)
and the [A2A 1.0 Agent Card summary](https://specification.website/spec/agent-readiness/a2a-agent-cards.md).

| Concern | Personal Agent Protocol (PAP) | A2A 1.0 | Elçi 0.0.2 |
| --- | --- | --- | --- |
| Who publishes | A company | An agent | A person (principal) |
| Discovery path | `/.well-known/poppy.json` | `/.well-known/agent-card.json` | `/.well-known/elci.json` |
| Version field | `protocol_version` | per interface `protocolVersion` | `protocol_version` |
| Publisher identity | `organization {name, domain}` | `provider` | `principal {name, domain}` |
| Agent keys | `jwks_uri` in client metadata | `signatures[]` (JWS) | `jwks` or `jwks_uri` per agent |
| Capabilities | `agent.protocols[]`, `apis[]` | `skills[]` with `tags` | `topics[]` (map to skill tags) |
| No agent on the other side | n/a | n/a | `fallback` email |
| Disclosure between a person's agents | n/a | n/a | need-to-know levels (spec §5) |

Design choices:

- **snake_case and `protocol_version`** follow PAP, so a parser for one reads the other easily.
- **`jwks` / `jwks_uri`** are standard JWK Set conventions (RFC 7517) also used by PAP client metadata.
- **`a2a_card`** lets an Elçi agent point to its full A2A Agent Card instead of duplicating skills.

Open: whether Elçi should be proposed to the PAP working group as an extension (PAP has an
`extensions` field) rather than a separate document. Tracked as an issue.
