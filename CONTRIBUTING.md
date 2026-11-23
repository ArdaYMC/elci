# Contributing to Elçi

Thanks for helping! Elçi is early, so the most valuable contributions right now are:

- **Issues about the spec**: unclear wording, a use case it cannot express, a security concern.
- **Conformance vectors** in `spec/vectors/` — they are what keeps every SDK honest.
- **SDKs in other languages** that pass the vectors (TypeScript is the next one).

## Ground rules

- Open an issue before a large change, so we can agree on the approach first.
- Every behaviour change to the protocol comes with a spec edit **and** a vector.
- Python: `cd python && pip install -e '.[dev]' && pytest`.

## AI-assisted contributions

AI tools are fine. What matters is that a person is accountable for the result:

- **Disclose it** in one line in the PR description.
- **Understand it**: you can explain every line and you ran the tests yourself.
- Fully autonomous agent PRs with no human in the loop will be closed.
