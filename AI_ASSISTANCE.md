# AI assistance disclosure

This project was specified, implemented and tested with **Claude Code** (Anthropic's coding agent)
under the direction and review of the repository owner.

## What the AI did

- Wrote the specification, both engines, the oracle and golden vectors, the backend, the React UI,
  the tests, the CI configuration and the documentation.
- Used several independent AI agents on purpose: the Python engine, the TypeScript engine and the
  vectors/oracle were written without seeing each other, then reconciled by a differential
  fuzzer. This reduces, but does not remove, the chance of a shared misreading of the spec.
- Ran the checks recorded in `docs/test-report.md` and fixed what they exposed.

## What the human owner is responsible for

- Direction, scope and acceptance decisions.
- Reviewing the code and deciding whether and when to publish.
- Checking each provider's current terms before pointing the tool at a real board.

## Not claimed

- No production users, accuracy, hiring outcomes or performance figures.
- Provider API behavior was taken from each provider's public documentation on 2026-10-13; the
  tests use synthetic payloads in those documented shapes, not recordings of real traffic.
- No independent human security audit has been performed.
