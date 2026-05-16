## Summary

<!-- 1–3 bullet points: what changed and why. -->

## Type

- [ ] feat
- [ ] fix
- [ ] perf
- [ ] refactor
- [ ] docs
- [ ] test
- [ ] build / ci
- [ ] chore

## Testing notes

<!-- How a reviewer can run/verify this. Commands, expected output, screenshots for UI. -->

## Documentation checklist

- [ ] `docs/architecture/` updated (module map / diagrams) — if module boundary changed
- [ ] ADR added in `docs/decisions/` — if a non-trivial decision was made
- [ ] Runbook in `docs/runbooks/` updated — if an operational concern is introduced
- [ ] `docs/api/openapi.json` regenerated (`make gen-api`) — if API changed
- [ ] `apps/*/README.md` or `packages/*/README.md` updated — if public contract changed
- [ ] All three locales (`ru/en/uz`) updated in `packages/i18n/locales/`

## Breaking changes

<!-- "None" or describe migration steps. -->

## Rollback plan

<!-- How to roll this back if it goes wrong in production. -->

## Linked issue

Closes #
