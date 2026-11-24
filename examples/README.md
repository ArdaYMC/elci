# Examples

## `three_agents.py`

One person (Arda), three agents, two counterparties, all on your machine:

| Agent | Public? | Knows | Talks to |
| --- | --- | --- | --- |
| Jarvy | no (not in the card) | the full calendar | only Arda's own agents |
| devbyarda | yes, `collaboration` | public profile | a brand's agent, over HTTP |
| acme-work | yes, `scheduling` | work matters for a fictional company | a supplier with no agent, by email |

What it shows:

1. Signed, delegated messages between two people's agents, verified on arrival.
2. **Need-to-know**: the brand learns that Thursday 14:00 is *busy*, never *why*.
3. **Email fallback**: the supplier gets a plain bilingual email and answers "2"; the reply is parsed and
   still waits for Arda's approval.
4. Every binding step carries a signed approval receipt.

```bash
pip install -e python
python examples/three_agents.py --yes     # drop --yes to approve each step yourself
```
