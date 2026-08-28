# @yupay/e2e — Playwright tests

End-to-end smoke + critical-path tests. Runs against a running stack
(`make dev` or staging).

```bash
make test-e2e             # against http://localhost:3000
WEB_BASE_URL=https://staging.yupay.io make test-e2e
```

## The affiliate suites need one worker

```bash
pnpm --filter @yupay/e2e test:affiliate
```

`affiliate-partner-site.spec.ts` and `affiliate-journey.spec.ts` both seed
partners by filing an application and signing in, and both endpoints sit behind
the two-axis `ip_guard`, which counts per IP. Run in parallel they trip the
throttle and fail for a reason that is not a bug. `--workers=1` exercises the
same paths without arguing with a protection that is working.

`affiliate-journey.spec.ts` writes eighteen numbered screenshots to
`e2e/journey/` — the whole programme as a sequence, from a partner reading the
pitch to an admin settling their payout. Three states in it are reached with
SQL rather than clicks (delivery, accrual, maturation), each documented in the
file with why no amount of clicking could produce it.
