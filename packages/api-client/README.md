# @yupay/api-client

Typed HTTP and WebSocket client for the YuPay backend. The HTTP layer is **generated**
from `docs/api/openapi.json`; do not hand-edit `src/generated/`.

```bash
pnpm --filter @yupay/api-client gen:api    # called by `make gen-api`
```

Consumers (web, miniapp) get a `createApiClient({ baseUrl, auth })` factory that returns the
generated typed client wired with TanStack Query hooks. The realtime layer (`./realtime`)
ships `OrderSocket` and a `useOrderUpdates(orderId)` hook.
