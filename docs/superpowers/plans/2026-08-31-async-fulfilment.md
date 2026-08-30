# Async fulfilment (Postgres-native queue) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the fulfilment saga out of the acquirer webhook: plan tasks in the payment transaction, NOTIFY on commit, and let the worker container drain them through the existing `process_task`.

**Architecture:** `start_for_order` splits into plan (unchanged, atomic with the payment) and execute (flag-off: inline as today; flag-on: leave `pending` + `pg_notify`). A claim-and-run core (`drain_pending_tasks`, SKIP LOCKED) lives in `fulfillment.service` so the api test suite owns its coverage; `apps/worker` becomes a thin asyncio loop around it (LISTEN + poll tick), replacing the never-used Dramatiq entrypoint.

**Tech Stack:** SQLAlchemy 2 async, raw asyncpg for LISTEN, Alembic, pytest+testcontainers. Dramatiq removed.

**Spec:** `docs/superpowers/specs/2026-08-31-async-fulfilment-design.md` — binding. Two corrections the code forced, both narrowing scope:

- The spec assumed `process_task` writes `next_attempt_at` for retryable failures. **It never does** (zero assignments in the module; the column's only reader is analytics). So the claim predicate is `status='pending'` alone, and the spec's "retries happen on schedule" line does not materialise — a `failed` task waits for the admin retry button exactly as it does today, in both modes. Adding scheduled retries would be new behaviour, out of scope.
- `retry_task` already flips `failed → pending` **and calls `process_task` inline** (`service.py:494-511`) — the spec's "admin retry stays inline" holds with zero changes.

## Global Constraints

- mypy --strict, ruff line 100, Google docstrings; comments say WHY.
- `fulfilment_async` defaults **False**: with the flag off, behaviour is byte-identical to today and the existing fulfilment suites (`test_fulfillment_routes.py`, `test_fulfillment_service_paths.py`, `test_fulfillment_manual_paths.py`, `test_admin_fulfillment_bulk_routes.py`, `test_fulfillment_list_ordering.py`, plus every payment/affiliate test that walks paid→delivered) must pass **untouched**. A modified existing test is a spec violation, not a fix.
- The NOTIFY channel name is `fulfillment_queue` everywhere.
- Only the api branches on the flag; the worker always drains what exists.
- `fulfillment` module coverage stays ≥ 95 % (§8).
- Conventional Commits with the two session trailers:

```
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0149WVtoHBWbESJhyFdhq5yE
```

---

### Task 1: flag, plan/execute split, NOTIFY on commit, claim index

**Files:**

- Modify: `apps/api/src/yupay/core/config.py` (two settings), `apps/api/src/yupay/modules/fulfillment/service.py` (`start_for_order` only)
- Create: `apps/api/migrations/versions/0062_fulfillment_pending_index.py` (revises `0061_auto_refund_sweep_indexes`)
- Test: `apps/api/tests/integration/test_fulfillment_async.py` (new)

**Interfaces:**

- Produces: settings `fulfilment_async: bool = False`, `fulfilment_poll_seconds: int = 5`; `start_for_order` unchanged signature, new flag-on behaviour (tasks left `pending`, `pg_notify('fulfillment_queue', order_id)` in-transaction); partial index `ix_fulfillment_tasks_pending ON fulfillment_tasks (created_at) WHERE status = 'pending'`.

- [ ] **Step 1: settings** — in `core/config.py`, after the risk block:

```python
    fulfilment_async: bool = Field(
        default=False,
        description=(
            "Execute fulfilment in the worker instead of inside the payment "
            "webhook. Off by default: the deploy that ships this must change "
            "production behaviour by zero bytes; the flip is an env change on "
            "the api container only — the worker always drains what exists."
        ),
    )
    fulfilment_poll_seconds: int = Field(
        default=5,
        description=(
            "Worker poll tick. LISTEN/NOTIFY does the real-time work; the "
            "tick only catches notifications lost to a worker restart, so it "
            "can be lazy. One indexed query per tick."
        ),
    )
```

- [ ] **Step 2: failing tests** (new file; copy the testcontainers scaffolding and the order/SKU factory from `test_fulfillment_service_paths.py` — same fixtures, so the async path is proven on the exact carts the sync tests use). The settings helper mirrors the one in `test_order_risk.py`:

```python
def _settings(**overrides: object) -> Settings:
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings(**base)
```

```python
async def test_flag_on_plans_but_does_not_execute(db_session, ...):
    """Tasks land `pending` in the caller's transaction; no supplier runs."""
    cfg = _settings(fulfilment_async=True)
    order = await _make_paid_order(db_session)          # existing factory
    tasks = await start_for_order(db_session, order_id=order.id, settings=cfg)
    assert [t.status for t in tasks] == ["pending"] * len(tasks)
    refreshed = await db_session.get(Order, order.id)
    assert refreshed.status == "fulfilling"             # planning happened
    # the mock fulfiller records invocations; none may have happened
    assert _mock_fulfiller_calls() == []


async def test_notify_rides_the_transaction(db_session, database_dsn, ...):
    """pg_notify is delivered on COMMIT and dropped on ROLLBACK — the
    property the whole design leans on, asserted against a real listener."""
    conn = await asyncpg.connect(database_dsn)          # raw, outside the ORM
    heard: list[str] = []
    await conn.add_listener("fulfillment_queue", lambda *a: heard.append(a[-1]))
    try:
        cfg = _settings(fulfilment_async=True)
        order = await _make_paid_order(db_session)
        await start_for_order(db_session, order_id=order.id, settings=cfg)
        await db_session.rollback()
        await asyncio.sleep(0.2)
        assert heard == []                              # rollback → silence
        order2 = await _make_paid_order(db_session)
        await start_for_order(db_session, order_id=order2.id, settings=cfg)
        await db_session.commit()
        await asyncio.sleep(0.2)
        assert heard == [order2.id]                     # commit → delivered
    finally:
        await conn.close()


async def test_flag_off_is_todays_behaviour(db_session, ...):
    """With the default settings the order walks straight to delivered —
    the same assertion the sync suite makes, from this file's fixtures."""
    order = await _make_paid_order(db_session)
    await start_for_order(db_session, order_id=order.id)
    refreshed = await db_session.get(Order, order.id)
    assert refreshed.status in ("fulfilled", "delivered")
```

(`database_dsn` = the container's URL with `+asyncpg` stripped: `settings.database_url.replace("postgresql+asyncpg://", "postgresql://")` — worth a tiny helper in the test file since Task 3's consumer needs the same conversion in prod code.)

- [ ] **Step 3: RED** — `COVERAGE_CORE=sysmon uv run pytest apps/api/tests/integration/test_fulfillment_async.py -q --no-cov` → FAIL (settings unknown / behaviour absent).
- [ ] **Step 4: implement the split.** In `start_for_order`, the execution loop currently reads (`service.py:~297`):

```python
    for task in new_tasks:
        if task.status == "pending":
            await process_task(db, task_id=task.id)
```

becomes:

```python
    cfg = settings or get_settings()
    if cfg.fulfilment_async:
        # Planned, not executed: the rows ARE the queue (they just landed in
        # the caller's transaction, atomically with the payment). The NOTIFY
        # rides the same transaction — Postgres delivers it on COMMIT and
        # drops it on ROLLBACK, so a nudge can neither outrun the commit nor
        # survive a rollback. The worker's poll tick covers a nudge lost to
        # a worker restart; nothing here needs to care.
        await db.execute(
            text("SELECT pg_notify('fulfillment_queue', :oid)"), {"oid": order_id}
        )
    else:
        for task in new_tasks:
            if task.status == "pending":
                await process_task(db, task_id=task.id)
```

`start_for_order` gains the keyword `settings: Settings | None = None` (both callers pass nothing; tests inject). Do not touch anything above the loop — planning is shared.

- [ ] **Step 5: migration 0062** — the claim query (Task 2) and the poll tick filter on `status='pending'`; §10 says the index lands with the query:

```python
def upgrade() -> None:
    op.create_index(
        "ix_fulfillment_tasks_pending",
        "fulfillment_tasks",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_fulfillment_tasks_pending", "fulfillment_tasks")
```

Docstring: tiny partial index; with the flag off it indexes an ~empty set and costs nothing.

- [ ] **Step 6: GREEN + gates** — the new file passes; then the untouched-suite proof: `COVERAGE_CORE=sysmon uv run pytest apps/api/tests/integration -q --no-cov -k "fulfillment or payment"` all green; `uv run mypy apps`; ruff both.
- [ ] **Step 7: Commit** — `feat(api/fulfillment): plan/execute split with NOTIFY-on-commit behind a flag`

---

### Task 2: the claim-and-run core

**Files:**

- Modify: `apps/api/src/yupay/modules/fulfillment/service.py`, `apps/api/src/yupay/modules/fulfillment/api.py` (export)
- Test: `apps/api/tests/integration/test_fulfillment_async.py` (extend)

**Interfaces:**

- Produces: `async def drain_pending_tasks(db: AsyncSession, *, limit: int = 20) -> int` — claims up to `limit` pending tasks `FOR UPDATE SKIP LOCKED` (oldest first), runs the existing `process_task` on each, settles their orders, returns how many it ran. Exported via `fulfillment.api` for the worker.
- Consumes: `process_task`, `_try_settle_order` (both existing).

- [ ] **Step 1: failing tests**

```python
async def test_drain_processes_pending_to_delivery(db_session, ...):
    cfg = _settings(fulfilment_async=True)
    order = await _make_paid_order(db_session)
    await start_for_order(db_session, order_id=order.id, settings=cfg)
    await db_session.commit()
    n = await drain_pending_tasks(db_session)
    assert n >= 1
    refreshed = await db_session.get(Order, order.id)
    assert refreshed.status in ("fulfilled", "delivered")


async def test_drain_with_nothing_pending_is_a_noop(db_session):
    assert await drain_pending_tasks(db_session) == 0


async def test_skip_locked_makes_duplicates_harmless(db_session, second_session, ...):
    """Two consumers on one order: every task runs exactly once. This is the
    entire concurrency story, so it gets a real two-session proof."""
    cfg = _settings(fulfilment_async=True)
    order = await _make_paid_order(db_session)
    await start_for_order(db_session, order_id=order.id, settings=cfg)
    await db_session.commit()
    ran = await asyncio.gather(
        drain_pending_tasks(db_session), drain_pending_tasks(second_session)
    )
    assert sum(ran) == <task count for the fixture cart>   # once total, split any way
    assert _mock_fulfiller_calls_per_task_max() == 1
```

(`second_session` — a second sessionmaker over the same testcontainer engine; the file's scaffolding source, `test_fulfillment_service_paths.py`, shows how sessions are built.)

- [ ] **Step 2: RED**, then implement:

```python
async def drain_pending_tasks(db: AsyncSession, *, limit: int = 20) -> int:
    """Claim and run pending fulfilment tasks. The worker's whole job.

    ``FOR UPDATE SKIP LOCKED`` is the entire concurrency story: duplicate
    notifications, a second worker replica, a poll tick racing a NOTIFY —
    whoever locks a row first runs it, everyone else skips. A crashed
    consumer's locks die with its connection and the next tick reclaims.

    Claims ``status='pending'`` only. ``failed`` stays a human decision
    (admin retry), exactly as in the synchronous mode — the async migration
    changes where work runs, never what counts as runnable.
    """
    rows = (
        await db.execute(
            select(FulfillmentTask.id, FulfillmentTask.order_id)
            .where(FulfillmentTask.status == "pending")
            .order_by(FulfillmentTask.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    ran = 0
    settled: set[str] = set()
    for task_id, order_id in rows:
        await process_task(db, task_id=task_id)
        settled.add(order_id)
        ran += 1
    for order_id in settled:
        await _try_settle_order(db, order_id=order_id)
    await db.flush()
    return ran
```

(If `_try_settle_order` turns out to be spelled differently, use whatever `retry_task` calls after processing — mirror that call site exactly; the point is that an order whose last task succeeded gets settled the same way the admin path settles it.)

- [ ] **Step 3: GREEN + gates** (same commands as Task 1 step 6) and the coverage check: `COVERAGE_CORE=sysmon uv run pytest apps/api/tests/integration -q -k fulfillment --cov=yupay.modules.fulfillment --cov-report=term | tail -5` — ≥ 95 %.
- [ ] **Step 4: Commit** — `feat(api/fulfillment): drain_pending_tasks, the queue's claim-and-run core`

---

### Task 3: the consumer loop replaces Dramatiq

**Files:**

- Create: `apps/worker/src/yupay_worker/consumer.py`
- Delete: `apps/worker/src/yupay_worker/main.py`, `apps/worker/src/yupay_worker/tasks/` (the whole never-used package)
- Modify: `apps/worker/pyproject.toml` (drop `dramatiq[redis,watch]`, add `asyncpg>=0.29` explicitly — it arrives transitively today, and a direct import deserves a direct dependency), root `pyproject.toml` (drop the `dramatiq.*` mypy override, ~line 168), `infra/docker/worker.Dockerfile` (CMD), `Makefile` (`dev-worker`), `docker-compose.yml` (worker `command:` if it overrides the Dockerfile — check line ~197; prod compose has no command override, verified)
- Test: `apps/worker/tests/test_consumer.py` (new — unit-level with fakes; the heavy path is already proven in Task 2's api suite)

**Interfaces:**

- Consumes: `fulfillment.api.drain_pending_tasks`, `yupay.core.db.get_engine` (one long-lived event loop → the pooled engine is safe here), `settings.database_url`, `settings.fulfilment_poll_seconds`.
- Produces: `python -m yupay_worker.consumer` as the container entrypoint; helper `raw_dsn(url: str) -> str` (strips `+asyncpg`).

- [ ] **Step 1: failing unit tests** (fakes, no DB — the loop's _logic_ is what worker tests own):

```python
def test_raw_dsn_strips_the_driver():
    assert raw_dsn("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


async def test_wait_wakes_on_notification_before_the_tick():
    """A set wake-event must cut the wait short of the tick."""
    wake = asyncio.Event()
    wake.set()
    started = time.monotonic()
    await _wait_for_wake_or_tick(wake, asyncio.Event(), seconds=5)
    assert time.monotonic() - started < 0.5
    assert not wake.is_set()          # the wait consumes the wake


async def test_wait_times_out_into_a_tick():
    started = time.monotonic()
    await _wait_for_wake_or_tick(asyncio.Event(), asyncio.Event(), seconds=0.2)
    assert time.monotonic() - started >= 0.2


async def test_listener_failure_falls_back_to_polling():
    """If LISTEN cannot be (re)established, ensure() must swallow the error
    (logging it) and return — the loop then lives on the poll tick alone.
    The connect dependency is injectable for exactly this test."""

    async def exploding_connect(dsn: str):  # noqa: ARG001
        raise OSError("no route to host")

    mgr = ListenerManager("postgresql://x", asyncio.Event(), connect=exploding_connect)
    await mgr.ensure()                # must not raise
    assert mgr.connected is False
```

(These fix the loop's seams: `_wait_for_wake_or_tick(wake, stop, *, seconds)` as a module-level coroutine, and `ListenerManager(dsn, wake, *, connect=asyncpg.connect)` with an `ensure()` that never raises and a `connected` property. Implement to these seams.)

- [ ] **Step 2: implement `consumer.py`** — the shape:

```python
"""The worker: drain the Postgres-native fulfilment queue.

LISTEN fulfillment_queue for instant wake-ups; a lazy poll tick
(fulfilment_poll_seconds) catches notifications lost to restarts. The rows
in fulfillment_tasks are the queue — this process holds no state worth
preserving and can be killed at any moment: row locks die with the
connection and the next tick reclaims the work.
"""

async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    wake = asyncio.Event()
    listener = ListenerManager(raw_dsn(get_settings().database_url), wake)
    log.info("worker.consumer.started", poll_seconds=...)
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    while not stop.is_set():
        await listener.ensure()                    # (re)connect w/ backoff, LISTEN
        await _wait_for_wake_or_tick(wake, stop, seconds=cfg.fulfilment_poll_seconds)
        if stop.is_set():
            break
        async with session_factory() as db:
            try:
                while await drain_pending_tasks(db) > 0:   # drain until dry
                    await db.commit()
                await db.commit()
            except Exception:
                log.exception("worker.consumer.drain_failed")
                await db.rollback()
    await listener.close()
    log.info("worker.consumer.stopped")


if __name__ == "__main__":
    asyncio.run(run())
```

The implementer refines commit placement to match how `drain_pending_tasks` and `process_task` manage the session (read `retry_task`'s pattern) — the invariant to preserve: each drained batch commits before the next wait, so a crash between batches loses nothing but locks.

- [ ] **Step 3: retire Dramatiq** — delete `main.py` + `tasks/`, drop the dependency and the mypy override, flip the Dockerfile CMD to `["python", "-m", "yupay_worker.consumer"]`, Makefile `dev-worker` to `cd apps/worker && uv run python -m yupay_worker.consumer`, dev-compose command if present. `uv lock` after the pyproject edits.
- [ ] **Step 4: gates** — worker tests green; `uv run mypy apps`; ruff both; and one live smoke: `make dev-worker` against the dev stack, one order through the storefront with `FULFILMENT_ASYNC=true` in the api env, watch it deliver (document the observed timing in the report).
- [ ] **Step 5: Commit** — `feat(worker): the Postgres-queue consumer replaces the idle Dramatiq entrypoint`

---

### Task 4: admin copy, docs, full-suite proof

**Files:**

- Modify: the admin release action's success message in `apps/admin/src/features/` (find the release button's toast — it must say the work was _started_; admin UI is Russian-only, follow what exists), AGENTS.md §2 (stack row), `docs/architecture/module-map.md`
- Create: `docs/decisions/0064-postgres-fulfilment-queue.md`, `docs/runbooks/fulfillment-queue.md`
- Test: none new — this task's proof is the whole suite

- [ ] **Step 1: admin copy** — locate the release-held-order success toast; if it implies completion («выдано»), change to «выдача запущена» + note that the order page shows progress. If it is already neutral, report that and change nothing.
- [ ] **Step 2: docs.**
  - AGENTS.md §2: Background work → `Postgres-native queue (FOR UPDATE SKIP LOCKED + LISTEN/NOTIFY) consumed by apps/worker; Dramatiq retired 2026-08; Temporal remains the deferred option for multi-step sagas`.
  - ADR-0064 (MADR, short): the carrier decision — why the deployed-but-never-used Dramatiq was retired in favour of the table that already carried the work; name the criteria (one system of record, backups cover the queue, async-native, NOTIFY-on-commit kills the truth-vs-nudge class) and the corrected fact that `next_attempt_at` had no writer, so no scheduled-retry behaviour was added.
  - Runbook: queue-depth SQL (`SELECT count(*) FROM fulfillment_tasks WHERE status='pending'` + age of oldest), worker liveness (the `worker.consumer.started` log line; container status), the flag's home (`secrets/api.env` only — the worker doesn't read it), what `pending` older than a minute means (worker down or drowning — check its logs), rollback procedure (flag off + api restart; worker drains leftovers).
  - `module-map.md`: worker row updated.
- [ ] **Step 3: full-suite proof** — `COVERAGE_CORE=sysmon uv run pytest -n auto -q` (known local `.env`-dependent failures — payme/uzum config, dev-login — are pre-existing and exempt; everything else green), `npx prettier --check docs`, mypy/ruff.
- [ ] **Step 4: Commit** — `docs(fulfillment): ADR-0064, queue runbook, stack row — and an honest release toast`

---

## Rollout (operator steps, post-merge/deploy)

1. Deploy, flag off. Worker now runs the consumer against an empty queue; verify the `worker.consumer.started` log line on prod.
2. `FULFILMENT_ASYNC=true` in `secrets/api.env`, restart api only. Watch one live order end-to-end; queue depth should touch zero between orders.
3. Rollback any time: flag off + api restart; the worker drains whatever is left.

## Self-review notes

- The two spec corrections (no `next_attempt_at` writer; `retry_task` already inline) are stated in the header so the executor does not "fix" the spec's ghost feature into existence.
- Task 1's NOTIFY test is the load-bearing one: it asserts the commit/rollback semantics the entire design rests on, against a real listener, not a mock.
- Existing-suite immutability is a Global Constraint precisely because it is the regression proof for flag-off mode; an implementer touching those files must treat it as a stop signal.
