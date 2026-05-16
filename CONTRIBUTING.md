# Contributing to YuPay

Thank you for contributing. Before you start, please read **[AGENTS.md](./AGENTS.md)** — it is
the single source of truth for coding standards, repo layout, testing rules, and the Definition
of Done. Both humans and AI agents follow the same playbook.

## Quick start

```bash
make bootstrap   # install all deps, set up pre-commit, generate API client
make dev         # bring up the full dev stack
make test        # run all tests
make lint        # lint everything
```

See [`docs/onboarding/local-setup.md`](./docs/onboarding/local-setup.md) for a detailed walkthrough.

## Workflow

1. Pick an issue (or open one) and discuss the approach if it isn't trivial.
2. Branch off `main`: `git checkout -b feat/<short-description>`.
3. Make changes following the rules in `AGENTS.md`.
4. Update or create docs (`docs/`) alongside your code — required, not optional.
5. Run `make lint typecheck test` locally.
6. Open a PR using the template. Fill in every checklist item.
7. Address review comments; squash-merge when approved.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) are enforced by `commitlint`.
Examples:

- `feat(api/orders): add idempotent order creation`
- `fix(web/checkout): handle expired guest token gracefully`
- `docs(decisions): record choice of Dramatiq over Celery`

## Questions

Open an issue with the `question` label, or ping `#yupay-dev` in Telegram.
