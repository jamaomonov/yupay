# Runbook — GitHub repository settings

> These rules cannot be enforced from code; they are configured in the GitHub UI. Keep this
> document in sync with the actual settings; deviations are violations of policy.

## Branch protection (`main`)

- Require a PR before merging.
- Require **1 approving review**; dismiss stale approvals on new commits.
- Require status checks to pass before merging. **Required checks**:
  - `lint-py`
  - `lint-ts`
  - `test-py`
  - `test-ts`
  - `openapi-drift`
  - `docs-check`
  - `commitlint`
- Require branches to be **up to date** before merging.
- Require **conversation resolution**.
- Require **linear history**.
- Restrict who can push to `main`: nobody (PRs only).
- Block force pushes; block deletions.

## Tags

- `v*.*.*` tags are protected; only org admins can create/delete.

## Secrets (Actions)

- `GHCR_PAT` — read+write packages, used by `build.yml`.
- `DEPLOY_SSH_KEY` — private key for the deploy user on the prod VPS.
- `DEPLOY_HOST` — VPS hostname.
- `SENTRY_AUTH_TOKEN` — for release upload.
- `R2_*` — Cloudflare R2 credentials (read-only for restore drills in CI).

## Environments

- `production` — protected, requires approval from `@release-managers` team.
- `staging` — protected, auto-approve.

## Dependabot

- Enabled for `pip`, `npm`, `docker`, `github-actions`.
- Weekly schedule; auto-merge for `patch` updates on dev dependencies after CI passes.

## Code scanning

- CodeQL enabled (`codeql.yml` workflow).
- Secret scanning + push protection enabled (GitHub Advanced Security if available).
