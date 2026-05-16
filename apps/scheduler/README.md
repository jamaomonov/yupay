# apps/scheduler — YuPay periodic jobs

APScheduler-based scheduler that runs as its own container. Jobs live in
`src/yupay_scheduler/jobs/`. Each job enqueues a Dramatiq actor — the scheduler
itself does **no** business work, only timing.
