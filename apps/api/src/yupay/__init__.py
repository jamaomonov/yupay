"""YuPay backend — modular monolith.

The public entrypoints are:

- ``yupay.main:app`` — FastAPI HTTP application
- ``yupay_worker.consumer`` — Postgres-queue fulfilment consumer (separate app, ``apps/worker``)
- ``yupay.scheduler`` — Periodic job registry
- ``yupay.bot`` — aiogram bot composition

Modules live under ``yupay.modules`` and expose narrow public interfaces via ``api.py``.
Importing internals of another module is prohibited; cross-module communication goes
through ``api.py`` or via the transactional outbox.
"""

__version__ = "0.0.1"
