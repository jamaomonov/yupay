# YuPay Documentation

This folder is the project's living documentation. **Update it in the same PR as the code
you change** — `AGENTS.md` § 5 explains exactly what change requires which doc update.

## Sections

| Folder                             | What lives here                                                              |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| [`architecture/`](./architecture/) | System overview, module map, data flow, Mermaid sequence diagrams, C4 model  |
| [`decisions/`](./decisions/)       | Architecture Decision Records (ADRs), numbered, using the MADR template      |
| [`runbooks/`](./runbooks/)         | Operational procedures: incident response, deploys, backups, secret rotation |
| [`api/`](./api/)                   | Generated OpenAPI schema (`openapi.json`) + auth/webhook notes               |
| [`onboarding/`](./onboarding/)     | Getting started for humans and agents, local setup, glossary                 |
| [`product/`](./product/)           | Domain glossary + business flow diagrams                                     |
| [`security/`](./security/)         | Threat model, PII inventory, webhook policy                                  |

## Conventions

- All diagrams in **Mermaid** (`.mmd` files alongside the markdown that embeds them).
- ADRs use the **MADR** template at `decisions/0000-template.md`. Numbering is strictly
  sequential.
- Cache keys are catalogued in `architecture/cache-keys.md` (one row per key, with TTL,
  invalidation rule, and owner module).
- Diagrams render natively on GitHub and are also published to GH Pages via the `docs.yml`
  workflow.
