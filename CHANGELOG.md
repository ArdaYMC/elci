# Changelog

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
