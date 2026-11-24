# Security policy

Elçi carries messages that can commit a person to something, so security bugs matter here.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting instead:
[Report a vulnerability](https://github.com/ArdaYMC/elci/security/advisories/new).

Include what an attacker can do, the steps or a failing test, and the version or commit. You will get
an answer within 7 days. Fixed issues are credited in the release notes unless you prefer otherwise.

## Supported versions

Elçi is a pre-1.0 draft. Only the latest commit on `main` gets fixes.

## Scope

In scope: the spec (`spec/`), the Python package (`python/`) and the examples' use of it.
Out of scope: the demo HTTP server's lack of TLS (documented as development-only).
