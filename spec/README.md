# Elçi protocol — draft 0.0.1

Status: working draft. Nothing here is stable. Key words MUST, SHOULD, MAY follow RFC 2119.

## 1. Roles

- **Principal**: a person. Has one or more agents.
- **Agent**: software acting for a principal within a **mandate** (topics, actions, disclosure rules).
- **Counterparty**: the other principal, reached through their agent or, if they have none, by email.

## 2. Discovery: the agent card

A principal publishes one document at:

```
https://<principal-domain>/.well-known/elci.json
```

It lists the principal's public agents. Schema: [`schemas/agent-card.schema.json`](schemas/agent-card.schema.json).
Each agent entry declares:

- `id`: stable URL identifying the agent;
- `topics`: what it may be contacted about (e.g. `scheduling`, `collaboration`);
- `endpoint`: HTTPS URL receiving Elçi messages;
- `keys`: public keys (JWK) used to verify its signed messages;
- `fallback`: how to reach the principal without an agent (`mailto:`).

A principal MAY keep internal agents (e.g. a coordinator with full memory) out of the card entirely.

Open question: align field names with the Personal Agent Protocol's `/.well-known/poppy.json` and
the A2A Agent Card once both drafts are reviewed (tracked in an issue).

## 3. Messages

Every message is a JSON envelope (schema: [`schemas/message.schema.json`](schemas/message.schema.json)) with
`from`, `to`, `on_behalf_of`, `topic`, `intent`, `body`, `thread`, `created_at`, and a detached
signature over the canonical JSON. Intents in 0.0.1:

| Intent | Meaning |
| --- | --- |
| `propose` | Offer options (e.g. time slots) |
| `query` | Ask a question within the topic |
| `answer` | Reply to a `query` |
| `accept` / `decline` | Close a proposal |
| `needs_human` | The agent cannot decide; its principal will be asked |

## 4. Mandate and delegation

An agent proves it speaks for its principal with a **delegation token** signed by a key listed in the
principal's card, naming the agent, the allowed topics and intents, and an expiry. Binding actions
(`accept` of anything that commits time or money) MUST carry a human approval receipt.

## 5. Need-to-know disclosure

Each agent has a disclosure policy: for every field it may reveal, the **level** it may reveal it at.
Example for availability: `none` < `busy_free` < `title` < `full`. An agent MUST answer at the lowest
level its policy allows for that counterparty, and MUST NOT leak fields above it. The same applies
between agents of the **same** principal.

## 6. Email fallback

If no card is found, or the counterparty's card has no agent for the topic, the sender MAY send an
email to the card's `fallback` (or a known address) that a human can read and answer. The email
carries a machine-readable footer with the thread id so replies can be matched. Parsing the human
reply is best effort and MUST be confirmed with the principal before any binding action.

## 7. Conformance

[`vectors/`](vectors/) holds input/expected-output pairs every implementation MUST pass.
