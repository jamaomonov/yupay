# apps/scheduler — YuPay periodic jobs

APScheduler-based scheduler that runs as its own container. Jobs live in
`src/yupay_scheduler/jobs/`. Each job calls the target module's service
functions directly (e.g. `click_timeout.py` calls `yupay.modules.click.service.cancel`)
— there is no actor/broker indirection; the scheduler itself does **no**
business work, only timing.
