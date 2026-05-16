# apps/worker — YuPay background workers

Dramatiq workers. Actors are registered in module-specific files under
`src/yupay_worker/tasks/<module>.py` and re-exported by `main.py` so a single Dramatiq
process consumes all queues.

## Run locally

```bash
make dev-worker
```
