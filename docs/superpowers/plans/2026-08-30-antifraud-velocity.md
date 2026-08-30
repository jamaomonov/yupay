# Antifraud identity windows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hold-for-review rules that see groups of orders sharing an identity (buyer, IP, device, target account), not just one order's amount — the per-order threshold is the thing the carders learned to undercut.

**Architecture:** `orders/risk.py` keeps its shape (decide → `hold_for_review`), gains an async `review_reason(db, order)` that gathers a 7-day window of paid orders sharing any identity with the current one, then runs **pure** decision functions over the gathered rows. SQL fetches; Python decides. `order_evidence` gains a `device_hash` column computed at capture and backfilled by migration.

**Tech Stack:** SQLAlchemy 2 async, Alembic, Pydantic v2 settings, pytest (+ testcontainers for integration).

**Spec:** `docs/superpowers/specs/2026-08-30-antifraud-velocity-design.md` — the rules, defaults, jitter formula, privacy constraints and measured justification all live there; this plan implements it verbatim.

## Global Constraints

- mypy --strict, ruff (line 100), Google docstrings on every public function.
- **Never** put a raw IP, user agent or target username into `order_events` payloads or alert texts (§9 + spec Privacy). Counts and reasons only.
- Every rule has an env off-switch; `0`/empty disables (spec Settings table).
- All new window rules run **only after payment succeeded** — nothing here rejects a payment.
- Coverage target for `orders/risk.py`: ≥ 95%.
- Conventional Commits; one logical change per commit as marked in tasks.

---

### Task 1: `device_hash` — model, capture, migration 0059

**Files:**

- Modify: `apps/api/src/yupay/modules/evidence/models.py`
- Modify: `apps/api/src/yupay/modules/evidence/service.py`
- Create: `apps/api/migrations/versions/0059_evidence_device_hash.py`
- Test: `apps/api/tests/integration/test_order_evidence.py` (extend)

**Interfaces:**

- Produces: `OrderEvidence.device_hash: str | None` (sha256 hex, 64 chars); pure helper `evidence.service.device_hash(user_agent, hints) -> str | None` used by capture and by tests.

- [ ] **Step 1: Write the failing tests** (extend `test_order_evidence.py`)

```python
from yupay.modules.evidence.service import device_hash
from yupay.modules.evidence.schemas import ClientHints


def test_device_hash_is_stable_and_component_sensitive() -> None:
    hints = ClientHints(timezone="Europe/Kiev", locale="uk-UA", screen="2560x1440@1")
    a = device_hash("Mozilla/5.0", hints)
    assert a == device_hash("Mozilla/5.0", hints)  # deterministic
    assert a != device_hash("Mozilla/5.0", ClientHints(timezone="Asia/Tashkent", locale="uk-UA", screen="2560x1440@1"))
    assert a is not None and len(a) == 64


def test_device_hash_of_nothing_is_none() -> None:
    # An evidence row with no UA and no hints must not produce a shared
    # "empty" fingerprint that links every unknown device into one identity.
    assert device_hash(None, None) is None
    assert device_hash("", ClientHints()) is None
```

And an integration assertion in the existing capture test: after `capture_for_order`, the stored row's `device_hash == device_hash(ua, hints)`.

- [ ] **Step 2: Run to verify failure** — `uv run pytest apps/api/tests/integration/test_order_evidence.py -q --no-cov` → FAIL (no `device_hash`).

- [ ] **Step 3: Implement**

`models.py` — after `client_hints`:

```python
    #: sha256 of ``user_agent | timezone | locale | screen`` — the device as a
    #: pseudonym, for the risk gate's shared-identity rule. Derived, so it
    #: lives and dies with this row's ``purge_after``.
    device_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

`service.py` — pure helper + one line in the insert values:

```python
def device_hash(user_agent: str | None, hints: ClientHints | None) -> str | None:
    """A stable pseudonym for the requesting device, or ``None``.

    ``None`` rather than a hash of emptiness: rows with no context must not
    all share one fingerprint and become a single giant false identity.
    """
    h = hints or ClientHints()
    parts = [user_agent or "", h.timezone or "", h.locale or "", h.screen or ""]
    if not any(parts):
        return None
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
```

In `capture_for_order`'s `.values(...)`: `device_hash=device_hash((request.headers.get("user-agent") or "")[:_UA_MAX] or None, hints),` (hash the same truncated UA that is stored, or the stored and hashed values drift).

- [ ] **Step 4: Migration** — `0059_evidence_device_hash.py`, revises `0058_order_affiliate_discount`:

```python
def upgrade() -> None:
    op.add_column("order_evidence", sa.Column("device_hash", sa.String(64), nullable=True))
    # Backfill must produce byte-identical hashes to the Python helper:
    # sha256 over "ua|tz|locale|screen". pgcrypto ships in infra/postgres/init
    # but the guard keeps the migration self-sufficient on fresh test DBs.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        UPDATE order_evidence SET device_hash = encode(digest(
            coalesce(user_agent, '') || '|' ||
            coalesce(client_hints->>'timezone', '') || '|' ||
            coalesce(client_hints->>'locale', '') || '|' ||
            coalesce(client_hints->>'screen', ''), 'sha256'), 'hex')
        WHERE coalesce(user_agent, '') || coalesce(client_hints->>'timezone', '')
              || coalesce(client_hints->>'locale', '') || coalesce(client_hints->>'screen', '') <> ''
        """
    )
    op.create_index("ix_order_evidence_ip", "order_evidence", ["ip"])
    op.create_index("ix_order_evidence_device_hash", "order_evidence", ["device_hash"])
    op.create_index("ix_orders_paid_at", "orders", ["paid_at"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_orders_paid_at", "orders", if_exists=True)
    op.drop_index("ix_order_evidence_device_hash", "order_evidence")
    op.drop_index("ix_order_evidence_ip", "order_evidence")
    op.drop_column("order_evidence", "device_hash")
```

Add a test in `test_order_evidence.py` proving SQL backfill equals the Python helper: insert a row with UA + hints via raw SQL with `device_hash=NULL`, run the backfill `UPDATE` statement, compare to `device_hash(...)`.

- [ ] **Step 5: Verify** — `uv run pytest apps/api/tests/integration/test_order_evidence.py -q --no-cov` → PASS; `uv run mypy apps` clean.

- [ ] **Step 6: Commit** — `feat(api/evidence): device fingerprint hash on order evidence`

---

### Task 2: Settings, jitter, async gate signature

**Files:**

- Modify: `apps/api/src/yupay/core/config.py`
- Modify: `apps/api/src/yupay/modules/orders/risk.py`
- Modify: `apps/api/src/yupay/modules/payments/service.py` (line ~523)
- Test: `apps/api/tests/unit/test_order_risk.py` (rewrite against pure helpers)

**Interfaces:**

- Produces: `_amount_reason(order, cfg) -> str | None` (pure, keeps rule 1); `_effective_threshold(order_id, cfg) -> Decimal`; `async review_reason(db, order, *, settings=None) -> str | None` (orchestrator — after this task it runs rule 1 only; Tasks 3–4 plug the window rules in).
- Consumes: nothing new.

- [ ] **Step 1: Settings** — in `core/config.py`, after `manual_review_threshold_usd` (descriptions in the same voice as neighbours; defaults from the spec table):

```python
    risk_sum_24h_usd: Decimal = Field(default=Decimal("25"))
    risk_sum_7d_usd: Decimal = Field(default=Decimal("60"))
    risk_velocity_24h: int = Field(default=5)
    risk_distinct_buyers_7d: int = Field(default=3)
    risk_liquid_brands: str = Field(default="roblox,telegram-stars,steam")
    risk_home_timezones: str = Field(default="Asia/Tashkent,Asia/Samarkand")
    risk_jitter: bool = Field(default=True)
```

(CSV strings, not lists: pydantic-settings would demand JSON in env vars for `list[str]`, and `RISK_LIQUID_BRANDS=roblox,steam` is what an operator will actually type. Parse with a small `_csv(value) -> frozenset[str]` in `risk.py`.)

- [ ] **Step 2: Failing unit tests** — rewrite `test_order_risk.py`: the four existing cases now call `_amount_reason` (same assertions, jitter off via `risk_jitter=False` in `_settings`), plus:

```python
def test_jitter_stays_inside_its_band_and_is_stable() -> None:
    cfg = _settings("40")  # risk_jitter left True here
    t1 = _effective_threshold("0192aaaa-bbbb-cccc-dddd-eeeeffff0001", cfg)
    assert t1 == _effective_threshold("0192aaaa-bbbb-cccc-dddd-eeeeffff0001", cfg)
    assert Decimal("24") <= t1 < Decimal("40")  # [0.6, 1.0) x base


def test_jitter_off_means_the_flat_threshold() -> None:
    cfg = _settings("40", jitter=False)
    assert _effective_threshold("any-id", cfg) == Decimal("40")
```

- [ ] **Step 3: Implement in `risk.py`**

```python
def _effective_threshold(order_id: str, cfg: Settings) -> Decimal:
    """Rule 1's threshold for this order — jittered so probing finds a band,
    not an edge. Deterministic per order id: retries and tests are stable."""
    base = cfg.manual_review_threshold_usd
    if not cfg.risk_jitter or base <= 0:
        return base
    u = int.from_bytes(hashlib.sha256(order_id.encode()).digest()[:8], "big") / 2**64
    return base * (Decimal("0.6") + Decimal("0.4") * Decimal(str(u)))


def _amount_reason(order: Order, cfg: Settings) -> str | None:
    threshold = _effective_threshold(order.id, cfg)
    if cfg.manual_review_threshold_usd > 0 and order.total_usd >= threshold:
        return REASON_LARGE_AMOUNT
    return None


async def review_reason(
    db: AsyncSession, order: Order, *, settings: Settings | None = None
) -> str | None:
    """Why this order must not be fulfilled automatically, or ``None``. (Docstring
    keeps the existing wording; add: window rules arrive in this module's
    gather/decide pair and never raise — a failed gather logs and falls back
    to the amount rule, because a broken risk query must not stop all sales.)"""
    cfg = settings or get_settings()
    return _amount_reason(order, cfg)  # window rules appended in Tasks 3-4
```

`SimpleNamespace` orders in tests need an `id` now — extend `_order()` with `id="0192..."`.

- [ ] **Step 4: Call site** — `payments/service.py`: `reason = await review_reason(db, order)`.

- [ ] **Step 5: Verify** — `uv run pytest apps/api/tests/unit/test_order_risk.py -q --no-cov` PASS; `uv run pytest -q --no-cov -k "payment and success" ` (the payment-success integration paths) PASS; mypy clean.

- [ ] **Step 6: Commit** — `feat(api/orders): jittered review threshold and async risk gate`

---

### Task 3: Window gather + rolling sum & velocity

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/risk.py`
- Test: `apps/api/tests/unit/test_order_risk.py` (pure rules), `apps/api/tests/integration/test_order_risk_windows.py` (new — SQL gather)

**Interfaces:**

- Produces:

```python
@dataclass(frozen=True)
class WindowOrder:
    id: str
    paid_at: datetime
    total_usd: Decimal
    buyer: str | None      # user_id or guest_email
    ip: str | None
    device: str | None
    targets: frozenset[str]

async def _gather(db, order) -> tuple[WindowOrder, list[WindowOrder]]
def _window_reason(current: WindowOrder, recent: list[WindowOrder], cfg: Settings) -> str | None
```

- Consumes: `device_hash` column (Task 1), settings (Task 2).

- [ ] **Step 1: Failing unit tests for the pure rule** (no DB). Test helpers, defined once at the top of the test module:

```python
def _cfg(
    sum24: str = "25", sum7d: str = "60", velocity: int = 5, buyers: int = 3,
    liquid: str = "roblox,telegram-stars,steam", home: str = "Asia/Tashkent,Asia/Samarkand",
) -> Settings:
    base = get_settings().model_dump()
    base.update(
        risk_sum_24h_usd=Decimal(sum24), risk_sum_7d_usd=Decimal(sum7d),
        risk_velocity_24h=velocity, risk_distinct_buyers_7d=buyers,
        risk_liquid_brands=liquid, risk_home_timezones=home, risk_jitter=False,
    )
    return Settings(**base)


_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _wo(
    minutes_ago: int, usd: str, *, buyer: str | None = "me@x.com",
    ip: str | None = None, device: str | None = None, targets: set[str] | None = None,
) -> WindowOrder:
    return WindowOrder(
        id=f"o-{minutes_ago}-{usd}", paid_at=_NOW - timedelta(minutes=minutes_ago),
        total_usd=Decimal(usd), buyer=buyer, ip=ip, device=device,
        targets=frozenset(targets or ()),
    )
```

(`_wo` defaults every order to the same buyer, so the plain-sum tests read
naturally; identity-specific tests override it. `_NOW` is fixed — the pure
rule compares `paid_at` values against `current.paid_at`, never the wall
clock, which is what makes these tests deterministic.)

The rule tests:

```python
def test_rolling_sum_24h_holds_the_order_that_crosses_the_cap() -> None:
    # Ten $18 Roblox orders was the real attack; three $11 is the same move
    # under the lowered threshold. Sum includes the current order.
    recent = [_wo(60, "11"), _wo(120, "11")]                 # same buyer
    assert _window_reason(_wo(0, "11"), recent, _cfg()) == REASON_ROLLING_SUM


def test_sum_counts_any_shared_key_not_only_buyer() -> None:
    recent = [_wo(60, "11", buyer="a@x.com", ip="203.0.113.7"),
              _wo(120, "11", buyer="b@x.com", ip="203.0.113.7")]
    current = _wo(0, "11", buyer="c@x.com", ip="203.0.113.7")
    assert _window_reason(current, recent, _cfg()) == REASON_ROLLING_SUM


def test_a_neighbour_sharing_nothing_is_invisible() -> None:
    recent = [_wo(60, "1000", buyer="stranger@x.com", ip="198.51.100.1", device="ffff")]
    assert _window_reason(_wo(0, "2", buyer="me@x.com", ip="203.0.113.7", device="aaaa"), recent, _cfg()) is None


def test_velocity_holds_the_sixth_order_in_a_day() -> None:
    recent = [_wo(i * 10, "1") for i in range(1, 6)]         # five paid, same buyer
    assert _window_reason(_wo(0, "1"), recent, _cfg()) == REASON_VELOCITY


def test_the_7d_cap_catches_a_slow_drip() -> None:
    recent = [_wo(60 * 24 * d, "9") for d in range(1, 7)]    # $9/day for 6 days = $54
    assert _window_reason(_wo(0, "9"), recent, _cfg()) == REASON_ROLLING_SUM  # 63 >= 60


def test_zeroes_disable_each_window_rule() -> None:
    cfg = _cfg(sum24="0", sum7d="0", velocity=0)
    recent = [_wo(10, "500") for _ in range(20)]
    assert _window_reason(_wo(0, "500"), recent, cfg) is None


def test_target_account_links_orders_with_nothing_else_shared() -> None:
    # The 7-orders-to-one-Stars-username pattern: buyers, IPs, devices all
    # differ; the destination does not.
    recent = [_wo(60, "11", buyer="a@x.com", ip="203.0.113.1", device="aa", targets={"durov"}),
              _wo(90, "11", buyer="b@x.com", ip="203.0.113.2", device="bb", targets={"durov"})]
    current = _wo(0, "11", buyer="c@x.com", ip="203.0.113.3", device="cc", targets={"durov"})
    assert _window_reason(current, recent, _cfg()) == REASON_ROLLING_SUM
```

- [ ] **Step 2: Run — FAIL.** Then implement.

`_window_reason` (pure; order of checks = spec rule order):

```python
def _shares_key(a: WindowOrder, b: WindowOrder) -> bool:
    return (
        (a.buyer is not None and a.buyer == b.buyer)
        or (a.ip is not None and a.ip == b.ip)
        or (a.device is not None and a.device == b.device)
        or bool(a.targets & b.targets)
    )


def _window_reason(current, recent, cfg):
    linked24 = [r for r in recent if _shares_key(current, r)
                and r.paid_at >= current.paid_at - timedelta(hours=24)]
    linked7d = [r for r in recent if _shares_key(current, r)]
    if cfg.risk_sum_24h_usd > 0 and current.total_usd + sum(r.total_usd for r in linked24) >= cfg.risk_sum_24h_usd:
        return REASON_ROLLING_SUM
    if cfg.risk_sum_7d_usd > 0 and current.total_usd + sum(r.total_usd for r in linked7d) >= cfg.risk_sum_7d_usd:
        return REASON_ROLLING_SUM
    if cfg.risk_velocity_24h > 0 and len(linked24) >= cfg.risk_velocity_24h:
        return REASON_VELOCITY
    return None
```

`_gather` (async; two queries, Python matching — the 7-day window is ≤ ~400 orders at current volume, stated in a comment as the assumption that makes scanning honest):

- Query A: `Order` LEFT JOIN `OrderEvidence`, `paid_at >= now()-7d`, `paid_at IS NOT NULL`, `id != order.id`, `purpose == "catalog"` — select id, paid_at, total_usd, user_id, guest_email, ip, device_hash.
- Query B: `OrderItem.order_id.in_(ids from A + [order.id])` → `fulfillment_data` per order; targets = lowercased/`@`-stripped string values, empty skipped.
- Build `WindowOrder`s; current order's own evidence row fetched by `order_id`.
- Wrap the whole gather in `try/except Exception: log.exception(...); return current-with-no-links, []` — a broken risk query must degrade to rule 1, not block sales (matches `hold_for_review`'s never-raise stance).

Wire into `review_reason`:

```python
    amount = _amount_reason(order, cfg)
    if amount is not None:
        return amount
    current, recent = await _gather(db, order)
    return _window_reason(current, recent, cfg)
```

- [ ] **Step 3: Integration test** (`test_order_risk_windows.py`, testcontainers style copied from `test_order_evidence.py`): create three paid guest orders sharing one IP via evidence rows (two prior + one current, $11 each), call `review_reason(db, current)` → `REASON_ROLLING_SUM`; a control order from a different IP/buyer → `None`. This proves the SQL joins, not the maths.

- [ ] **Step 4: Verify** — targeted tests PASS, mypy, ruff.

- [ ] **Step 5: Commit** — `feat(api/orders): rolling-sum and velocity rules over identity windows`

---

### Task 4: Shared identity + geo mismatch + alerts

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/risk.py`
- Test: extend both risk test files

**Interfaces:**

- Produces: `REASON_SHARED_IDENTITY`, `REASON_GEO_MISMATCH`, their `HOLD_ALERT_TEXT` entries; `_geo_reason(order_is_guest, item_brand_slugs, tz, cfg) -> str | None` (pure). `_gather` return grows a `GeoContext` (`is_guest`, `brand_slugs: frozenset[str]`, `timezone: str | None`).

- [ ] **Step 1: Failing unit tests**

```python
def test_one_device_serving_three_buyers_is_held() -> None:
    recent = [_wo(60, "1", buyer="a@x.com", device="dd"),
              _wo(90, "1", buyer="b@x.com", device="dd")]
    assert _window_reason(_wo(0, "1", buyer="c@x.com", device="dd"), recent, _cfg()) == REASON_SHARED_IDENTITY


def test_one_buyer_on_two_devices_is_not_shared_identity() -> None:
    # A person with a phone and a laptop is not a fraud ring.
    recent = [_wo(60, "1", buyer="a@x.com", device="d1"), _wo(90, "1", buyer="a@x.com", device="d2")]
    assert _window_reason(_wo(0, "1", buyer="a@x.com", device="d3"), recent, _cfg()) is None


def test_guest_liquid_brand_foreign_tz_is_held() -> None:
    assert _geo_reason(True, frozenset({"roblox"}), "Europe/Kiev", _cfg()) == REASON_GEO_MISMATCH


def test_signed_in_or_home_tz_or_illiquid_brand_passes() -> None:
    cfg = _cfg()
    assert _geo_reason(False, frozenset({"roblox"}), "Europe/Kiev", cfg) is None
    assert _geo_reason(True, frozenset({"roblox"}), "Asia/Tashkent", cfg) is None
    assert _geo_reason(True, frozenset({"free-fire"}), "Europe/Kiev", cfg) is None
    assert _geo_reason(True, frozenset({"roblox"}), None, cfg) is None       # no tz = no claim
    assert _geo_reason(True, frozenset({"free-fire", "roblox"}), "Europe/Kiev", cfg) == REASON_GEO_MISMATCH  # any liquid item


def test_empty_lists_disable_the_geo_rule() -> None:
    assert _geo_reason(True, frozenset({"roblox"}), "Europe/Kiev", _cfg(liquid="", home="")) is None
```

- [ ] **Step 2: Implement.** Shared-identity check appended inside `_window_reason` (after velocity): among `linked7d` rows matched **by ip or device specifically**, count distinct non-None buyers ∪ {current.buyer}; ≥ `risk_distinct_buyers_7d` → `REASON_SHARED_IDENTITY`. `_geo_reason` per the tests; both wired into `review_reason` (geo last, per spec rule order — geo is 5th). Gather learns brand slugs (join `order_items → skus → products → brands` for the current order only) and the tz from the current evidence row's `client_hints->>'timezone'`.

- [ ] **Step 3: Alert texts** — extend `HOLD_ALERT_TEXT` (pattern of the existing two; PII-free):

```python
    REASON_ROLLING_SUM: (
        "🔍 Серия заказов — на проверке",
        "Сумма связанных заказов за окно превысила лимит. Смотри всю серию по "
        "покупателю/IP в админке, не только этот заказ: выдай или верни по каждому.",
    ),
    REASON_VELOCITY: (
        "🔍 Слишком частые заказы — на проверке",
        "Больше N оплаченных заказов одной личности за сутки. Проверь серию целиком.",
    ),
    REASON_SHARED_IDENTITY: (
        "🔍 Один источник — разные покупатели",
        "С одного IP/устройства платят несколько «разных» покупателей. Найди в "
        "админке все заказы этой группы, прежде чем что-то выдавать: выпуск "
        "одного заказа из связки обесценивает правило.",
    ),
    REASON_GEO_MISMATCH: (
        "🔍 Гость из чужой таймзоны на ликвидном товаре",
        "Roblox/Stars, гость, таймзона вне домашнего списка. Классический "
        "профиль кардера — но им может оказаться и честный покупатель в "
        "поездке: посмотри и реши.",
    ),
```

(`N` in the velocity text becomes the real number via `.format(...)`? No — keep the static text; the count goes in the event payload, same as existing entries carry no numbers.)

`hold_for_review` gains `detail: dict[str, int] | None = None` merged into the event payload — counts only (`{"linked_orders_24h": 5}`), never identities.

- [ ] **Step 4: Integration test** — guest order for a liquid-brand SKU with evidence tz `Europe/Kiev` → held with `REASON_GEO_MISMATCH`; same order with `user_id` set → fulfilled. Reuse the brand/SKU factory from existing integration tests.

- [ ] **Step 5: Verify + commit** — `feat(api/orders): shared-identity and geo-mismatch rules`

---

### Task 5: Docs, coverage, full suite

**Files:**

- Create: `docs/decisions/0062-antifraud-identity-windows.md` (MADR, short — decision: rules-not-ML, tz-not-geoip, hold-not-block; links the spec)
- Create: `docs/runbooks/order-held-for-review.md` — extend if it exists, else create: what each of the six reasons means, how to find the linked group in the admin orders list, release vs refund guidance, and the env kill switches with exact variable names
- Modify: `apps/api/src/yupay/modules/orders/risk.py` module docstring (drop "the next rule" prophecy — it came true)
- Modify: `docs/architecture/module-map.md` (one line: risk gate now consults evidence)

- [ ] **Step 1: Write the three docs.** The runbook's kill-switch table is the load-bearing part: `RISK_SUM_24H_USD=0`, `RISK_SUM_7D_USD=0`, `RISK_VELOCITY_24H=0`, `RISK_DISTINCT_BUYERS_7D=0`, `RISK_LIQUID_BRANDS=`, `RISK_HOME_TIMEZONES=`, `RISK_JITTER=false`, plus `MANUAL_REVIEW_THRESHOLD_USD` itself.
- [ ] **Step 2: Coverage** — `uv run pytest apps/api/tests/unit/test_order_risk.py apps/api/tests/integration/test_order_risk_windows.py --no-cov -q` then the suite-wide run: `COVERAGE_CORE=sysmon uv run pytest -n auto -q` and check `risk.py` ≥ 95% in the report.
- [ ] **Step 3: Full gates** — `uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps`; `npx prettier --check docs`.
- [ ] **Step 4: Commit** — `docs(orders): ADR-0062, held-order runbook, module map`

---

## Rollout (operator steps, after merge+deploy)

1. Deploy ships rules live with defaults — no env change needed on day one.
2. Watch `order_held_for_review` alert volume for a week; tune windows via env if the queue is noisy.
3. Decide whether `MANUAL_REVIEW_THRESHOLD_USD` goes back up from 12 — rule 2 now guards the ground the lowered threshold was covering.

## Self-review notes

- Existing unit tests keep their four scenarios but move to `_amount_reason`; no test is deleted.
- `paid_at` on the current order: at gate time `mark_paid` has already stamped it — the integration tests must set `paid_at` on fixture orders explicitly, matching that reality.
- Wallet top-ups: unchanged — the call site returns before the gate; no new code path to test beyond the existing one.
- The gather's `purpose == "catalog"` filter keeps wallet top-ups out of windows too: a legit top-up spree must not feed the sum that holds a catalog order.
