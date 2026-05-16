# @yupay/e2e — Playwright tests

End-to-end smoke + critical-path tests. Runs against a running stack
(`make dev` or staging).

```bash
make test-e2e             # against http://localhost:3000
WEB_BASE_URL=https://staging.yupay.io make test-e2e
```
