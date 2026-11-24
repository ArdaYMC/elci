<p align="center">
  <img src="https://raw.githubusercontent.com/ArdaYMC/elci/main/docs/assets/banner.svg" alt="Elçi: your agent talks to their agent, safely" width="100%">
</p>

# elci

Reference implementation of [Elçi](https://github.com/ArdaYMC/elci), an open protocol for personal
AI agents to talk to other people's agents, safely: signed messages, delegated mandates,
need-to-know disclosure, verifiable human approval, and an email fallback for people without an agent.

> Alpha. The spec is a working draft and the API may change between minor versions.

## Install

```bash
pip install elci            # library
pip install 'elci[mcp]'     # plus the elci-mcp server for Claude Code and other MCP hosts
```

## Quick look

```python
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from elci import Agent, Delegation, issue_delegation

principal_key, agent_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
agent_id = "https://arda.example/agents/devbyarda"
token = issue_delegation(
    Delegation("arda.example", agent_id, ("collaboration",), ("propose", "answer"), int(time.time()) + 3600),
    principal_key,
)
agent = Agent(agent_id, "arda.example", agent_key, token)
message = agent.message(to="https://brand.example/agents/partnerships", topic="collaboration",
                        intent="propose", body={"slots": ["2026-11-27T11:00"]})
```

The receiving side runs `elci.Inbox(own_card).accept(message)`, which checks the sender's card,
domain, freshness, signature, delegation, approval receipt and replays.

## Use it from Claude Code

```bash
pip install 'elci[mcp]'
claude mcp add elci -- elci-mcp
```

## Links

- [Specification](https://github.com/ArdaYMC/elci/tree/main/spec)
- [Three-agent demo](https://github.com/ArdaYMC/elci/tree/main/examples)
- [Security policy](https://github.com/ArdaYMC/elci/security/policy)
- [Contributing](https://github.com/ArdaYMC/elci/blob/main/CONTRIBUTING.md)

## Develop

```bash
git clone https://github.com/ArdaYMC/elci && cd elci/python
pip install -e '.[dev]'
pytest
```
