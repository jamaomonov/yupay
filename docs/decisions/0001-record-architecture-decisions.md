# 0001. Record architecture decisions

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: process

## Context

YuPay is a greenfield project that will accumulate many non-obvious architectural choices
(modular monolith vs microservices, payment abstraction, FX strategy, ledger model, brokers,
i18n approach, deployment topology). Without a written record, future contributors — human
or AI — cannot tell whether a given pattern is a deliberate choice or accidental code.

## Decision

We will record every non-trivial architectural decision as an **Architecture Decision
Record (ADR)** following the [MADR](https://adr.github.io/madr/) template, stored in
`docs/decisions/NNNN-<title>.md`. The template lives at `docs/decisions/0000-template.md`.

Numbering is strictly sequential. Status moves through `Proposed → Accepted → Deprecated →
Superseded by NNNN`. ADRs are **never deleted** — they are superseded.

## Consequences

- New dependencies, frameworks, infra components, and cross-cutting patterns must be paired
  with an ADR in the same PR.
- The `docs-check` CI step will eventually verify that PRs touching architectural surfaces
  reference an ADR.
- The `AGENTS.md` rules direct agents and humans alike to write an ADR when in doubt.

## References

- [MADR template](https://adr.github.io/madr/)
- Michael Nygard, ["Documenting Architecture Decisions"](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
