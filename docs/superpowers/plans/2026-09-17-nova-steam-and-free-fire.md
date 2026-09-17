# NOVA for Steam and Free Fire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sell Free Fire CIS through NOVA (cheaper on all nine SKUs), add the ten Free Fire items only NOVA carries, make NOVA a switchable reserve for Steam wallet top-ups, and report margin against what a supplier actually charged rather than against the face value.

**Architecture:** One new client method and one branch in the existing `NovaFulfiller` for NOVA's separate Steam endpoint, discriminated by a sentinel mapping. One new branch in `orders.revenue.margin_usd_expr`, fed by a cost the fulfilment saga records on the order line when a supplier states what it charged. Everything else is catalogue data: mappings, sourcing rules, a product and ten SKUs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, httpx, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-09-17-nova-steam-and-free-fire-design.md`

## Global Constraints

- **`gross − margin == cost` is the invariant of `orders/revenue.py`.** `charged_usd_expr` and `margin_usd_expr` are written to keep it; a change to one is a change to both or a bug. Assert it in a test.
- **No existing row may change how it reports.** Every variable line written before this change has `OrderItem.cost_usdt IS NULL` (0 of 316 on prod) and must keep taking the old branch.
- **A cost is recorded only when the supplier states it.** Never inferred from a rate, never defaulted. A supplier that says nothing leaves the column NULL.
- **NOVA money grading is unchanged** (ADR-0081): their create spends, so a failure on or after the call is `UNKNOWN`; 400/403/404 are `RETURNED`; a low-balance refusal is the `supplier_low_balance` stall.
- **NOVA stays a reserve.** `RESERVE_SUPPLIERS` means auto sourcing never picks it; every SKU that should reach NOVA needs an explicit `force_supplier` rule, including the ten new ones.
- **A new product must not break the brand's player check.** `brand_check_field` returns a check only when every active product of a brand agrees on it (ADR-0079). `free-fire-packs` copies `required_fields` from `free-fire-diamonds` verbatim.
- Never log a raw `player_id`, `steam_login`, nickname or API key.
- `ruff` line-length 100, `mypy --strict` (**run it from the repo root over `apps`, which includes tests**), Google docstrings, ≥95 % coverage for supplier adapters.
- No pushing, no deploying, no prod database writes. Branch: `feat/nova-steam-and-free-fire`.

---

## File Structure

| File                                                              | Responsibility                                                              |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `apps/api/src/yupay/modules/fulfillment/suppliers/nova_client.py` | `create_steam_order`, and folding their `novaDebit` into the returned order |
| `apps/api/src/yupay/modules/fulfillment/suppliers/nova.py`        | the Steam branch, and reporting the charge in `extra_metadata`              |
| `apps/api/src/yupay/modules/fulfillment/service.py`               | recording that charge on the order line                                     |
| `apps/api/src/yupay/modules/orders/revenue.py`                    | the margin branch that reads it                                             |
| `scripts/seed/2026-09-17_nova_mappings.py`                        | Free Fire category, the by-name overrides, the `force_supplier` rules       |
| `scripts/seed/2026-09-18_free_fire_nova_only.py`                  | the product, the ten SKUs, their mappings and rules                         |
| `docs/decisions/0082-*.md`, `docs/runbooks/nova.md`               | the decision and the operator's half                                        |

---

## Task 1: NOVA's Steam endpoint

**Files:**

- Modify: `apps/api/src/yupay/modules/fulfillment/suppliers/nova_client.py`, `apps/api/src/yupay/modules/fulfillment/suppliers/nova.py`
- Test: `apps/api/tests/contract/test_nova_client.py`, `apps/api/tests/unit/test_nova_fulfiller.py`

**Interfaces:**

- Produces: `NovaClient.create_steam_order(*, steam_login, amount_usd, idempotency_key) -> dict`, the sentinel `nova.STEAM_SENTINEL = "steam-topup"`, and `supplier_charged_usd` in a result's `extra_metadata` (Task 2 consumes that).

- [ ] **Step 1: Write the failing tests**

Contract (`test_nova_client.py`), three cases:

```python
@respx.mock
async def test_a_steam_order_is_a_different_endpoint_and_answers_201() -> None:
    """Their Steam top-up is not their games top-up: no category, no offer, a
    login and an amount — and a `201`, where the games one answers `200`."""
    route = respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(
            201,
            json={
                "ok": True,
                "order": {"id": "ord-9", "status": "created"},
                "novaDebit": {"amountUsd": "9.80", "balanceUsd": "90.20"},
            },
        )
    )
    order = await _client().create_steam_order(
        steam_login="someone", amount_usd=Decimal("10"), idempotency_key="task-7"
    )
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"steamLogin": "someone", "currency": "USD", "amount": "10.00"}
    assert route.calls.last.request.headers["Idempotency-Key"] == "task-7"
    assert order["id"] == "ord-9"
    # What we were charged is theirs to state and ours to record: it arrives
    # beside the order, not inside it, and one shape has to answer it.
    assert order["chargedUsd"] == "9.80"


@respx.mock
async def test_a_steam_amount_carries_at_most_two_decimals() -> None:
    """Their schema refuses more, and a request refused for a formatting
    reason is a customer waiting on nothing."""
    route = respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(201, json={"ok": True, "order": {"id": "ord-9"}})
    )
    await _client().create_steam_order(
        steam_login="someone", amount_usd=Decimal("10.005"), idempotency_key="k"
    )
    assert json.loads(route.calls.last.request.content)["amount"] == "10.01"


@respx.mock
async def test_a_steam_plan_refusal_keeps_its_sentence() -> None:
    respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(
            400,
            json={
                "ok": False,
                "error": "plan does not allow this amount",
                "availablePlans": ["silver", "gold"],
                "balanceUsd": "9.10",
            },
        )
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().create_steam_order(
            steam_login="someone", amount_usd=Decimal("500"), idempotency_key="k"
        )
    assert excinfo.value.status == 400
    assert "plan does not allow" in str(excinfo.value)
```

Unit (`test_nova_fulfiller.py`), four cases: a Steam mapping sends the login and the line's dollar amount and never touches `create_topup_order`; a games mapping never reaches the Steam call; a line with no `steam_login` is refused before any call with `RETURNED`; the charge reaches `extra_metadata["supplier_charged_usd"]`.

- [ ] **Step 2: Run them, watch them fail.** `cd apps/api && uv run pytest tests/contract/test_nova_client.py tests/unit/test_nova_fulfiller.py -q`

- [ ] **Step 3: The client method**

```python
    async def create_steam_order(
        self, *, steam_login: str, amount_usd: Decimal, idempotency_key: str
    ) -> dict[str, Any]:
        """Top up a Steam wallet. Their Steam endpoint, not the games one.

        Different in three ways that all matter: it takes a login and an amount
        rather than a category and an offer, it answers ``201``, and what it
        charges us is **not** the amount — their plan discount applies, which is
        why the debit they report beside the order is folded in below.

        Args:
            steam_login: The customer's login. Never logged.
            amount_usd: Face value in dollars — what the customer receives. Sent
                with at most two decimals, which their schema requires; rounding
                is half-up so a fraction of a cent is never taken off what was
                bought.
            idempotency_key: Required, as on every purchase of theirs. A reused
                key is refused with a ``409``, never replayed.
        """
        amount = amount_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        body = await self._request(
            "POST",
            "/api/v2/steam-topup/order",
            json={"steamLogin": steam_login, "currency": "USD", "amount": f"{amount}"},
            headers={"Idempotency-Key": idempotency_key[:255]},
        )
        return _order_with_debit(body)
```

and the shared helper both create methods now return through:

```python
def _order_with_debit(body: dict[str, Any]) -> dict[str, Any]:
    """Their order, with what they charged us folded in.

    A create answers ``{ok, order, novaDebit}``: the order says what was bought
    and ``novaDebit.amountUsd`` says what it cost us, and those are different
    numbers for Steam, where a plan discount applies. A later ``GET`` of the
    same order carries ``chargedUsd`` instead. One key has to answer "what were
    we charged" on both paths or the caller needs to know which call it is
    holding — so the create's debit is written under the name the ``GET`` uses.
    """
    order = body.get("order")
    if not isinstance(order, dict):
        return {}
    debit = body.get("novaDebit")
    amount = debit.get("amountUsd") if isinstance(debit, dict) else None
    return {**order, "chargedUsd": amount} if amount is not None else dict(order)
```

`create_topup_order` returns through the same helper. Import `Decimal` and `ROUND_HALF_UP`.

- [ ] **Step 4: The adapter branch**

In `nova.py`:

```python
#: A mapping whose ``external_product_id`` is this is a Steam wallet top-up,
#: not a game: their Steam endpoint takes a login and an amount and has no
#: category at all, so there is no real id to put here.
#:
#: A sentinel rather than a fourth ``kind`` for the reason ADR-0081 gives about
#: the validate namespace: ``ck_sku_supplier_mapping_kind`` allows only
#: ``voucher|game|gift``, and the admin's mapping wizard coerces whatever it
#: loads to ``voucher|game`` when an operator saves the page. A sentinel in a
#: column the wizard round-trips untouched survives that; a new kind does not.
STEAM_SENTINEL = "steam-topup"
```

`fulfill` dispatches on it immediately after loading the mapping and before reading `offer_id`, then `_fulfill_steam` mirrors the games path: refuse `qty > 1` and a missing `steam_login` before any call (`_NOTHING_SPENT`); call `create_steam_order` with `Decimal(str(item.unit_price_usd))`; catch `NovaError` (low-balance first, then `_refusal_money`, message redacted with `_redacted(str(exc), steam_login)`) and `NovaUnavailableError` (`_MAY_HAVE_SPENT`); pass the object through `_result` and the same id-less-create guard.

`_result` gains the charge, on every outcome — the money left us whether or not the order finished:

```python
def _charged_usd(obj: dict[str, Any]) -> str | None:
    """What they say they took, as a decimal string, or ``None``.

    ``chargedUsd`` is what a fetched order carries and what the client folds a
    create's ``novaDebit`` into; ``charged_usd`` is the snake-case twin their
    API also returns. For a game these equal the price; for Steam they do not,
    which is the whole point of recording them.
    """
    for key in ("chargedUsd", "charged_usd"):
        value = obj.get(key)
        if value not in (None, ""):
            return str(value)
    return None
```

and `_meta(status)` becomes `_meta(status, obj)` so every result carries
`{"supplier": "nova", "nova_status": status, **({"supplier_charged_usd": charged} if charged else {})}`.

- [ ] **Step 5: Tests green, lint, typecheck, coverage ≥95 %, commit**

```bash
git commit -m "feat(api/fulfillment): top up Steam wallets through NOVA"
```

---

## Task 2: Report margin against what we were actually charged

**Files:**

- Modify: `apps/api/src/yupay/modules/fulfillment/service.py` (after the metadata merges at ~706 and ~2242), `apps/api/src/yupay/modules/orders/revenue.py` (`margin_usd_expr`)
- Test: `apps/api/tests/unit/` (the revenue/margin suite — find it with `rg -l margin_usd_expr apps/api/tests`), plus an integration case in the fulfilment suite

**Interfaces:**

- Consumes: `supplier_charged_usd` in a result's `extra_metadata` (Task 1).
- Produces: `OrderItem.cost_usdt` populated on variable-amount lines; one new branch in `margin_usd_expr`.

**Read first:** the docstrings of `charged_usd_expr` and `margin_usd_expr`. They explain why the two must change together and why a cost is frozen rather than read live (ADR-0051, ADR-0053). This task adds a source of truth that is better than both: what the supplier actually took.

- [ ] **Step 1: Write the failing tests**

- A variable line with `cost_usdt = 9.80`, `unit_price_usd = 10`, `qty = 1`, multiplier `1.10`: gross `11.00`, margin `1.20`.
- The same line with `cost_usdt = NULL`: margin `1.00` — the old branch, unchanged.
- **The invariant**, asserted directly on both: `gross − margin == cost`, where cost is `9.80` and `10.00` respectively.
- A fixed-price line is untouched by any of it.
- A discounted variable line: the discount comes off gross and margin alike and the invariant still holds.
- In the fulfilment suite: a NOVA result carrying `supplier_charged_usd` writes it to the item's `cost_usdt` when the SKU is variable-amount; a result without it writes nothing; a **fixed**-price SKU is left alone even when the metadata carries a charge.

- [ ] **Step 2: Run them, watch them fail.**

- [ ] **Step 3: Record the charge**

In `fulfillment/service.py`, a helper called from both metadata-merge sites:

```python
async def _record_supplier_charge(
    db: AsyncSession, *, item: OrderItem, extra: dict[str, Any]
) -> None:
    """Freeze what the supplier actually took onto a variable-amount line.

    Only variable-amount SKUs, and only when the supplier states a figure.

    A fixed SKU already froze its cost at checkout from the catalogue
    (ADR-0053), and overwriting that with a supplier's own number would change
    how every fixed line reports — a different decision, not this one. A
    variable line froze nothing, because until now there was nothing to freeze:
    ``margin_usd_expr`` assumed a dollar of wallet costs a dollar. NOVA's Steam
    is the first supplier for which that is false, and a number we were charged
    beats an assumption about what we would be.

    Written once and never overwritten: the first statement is the create's,
    and a later poll restating it must not move a figure the margin has already
    been reported against.
    """
    charged = str(extra.get("supplier_charged_usd") or "").strip()
    if not charged or item.cost_usdt is not None:
        return
    variable = (
        await db.execute(select(Sku.variable_amount).where(Sku.id == item.sku_id))
    ).scalar_one_or_none()
    if not variable:
        return
    with contextlib.suppress(InvalidOperation):
        item.cost_usdt = Decimal(charged)
```

- [ ] **Step 4: Read it in the margin**

In `margin_usd_expr`, **before** the existing variable branch:

```python
        (
            and_(Sku.variable_amount.is_(True), OrderItem.cost_usdt.isnot(None)),
            OrderItem.qty * OrderItem.unit_price_usd * variable_multiplier
            - OrderItem.qty * OrderItem.cost_usdt
            - _line_discount(),
        ),
```

and extend the function's docstring: the variable branch's `(multiplier - 1)` encodes "a dollar of wallet costs a dollar", which is true of Waxpeer and G-Engine and false of NOVA, whose plan discount means $10 of wallet costs $9.80; a line that knows what it cost uses it, and a line that does not keeps the assumption it was written under.

- [ ] **Step 5: Tests green, `mypy` from the repo root, commit**

```bash
git commit -m "fix(api/orders): report Steam margin against the real cost basis"
```

---

## Task 3: Free Fire CIS through NOVA

**Files:**

- Modify: `scripts/seed/2026-09-17_nova_mappings.py`

**Interfaces:** consumes the matcher and upsert already in that file.

- [ ] **Step 1: Add the category and the overrides**

`BRAND_CATEGORIES` gains `"free-fire": "free_fire_cis"`, with a measured note like its neighbours: all six diamond denominations pair on number and unit; the three memberships carry no number, so they come from an explicit table:

```python
#: SKUs whose label is a name rather than a denomination, paired by hand.
#:
#: The matcher keys on a number and a unit, which is what makes it safe — and
#: a membership has neither. Pairing these by *name* instead would be fuzzy
#: matching on the one axis where a wrong answer routes money to the wrong
#: product, so they are listed here, read once by a human, or not mapped at all.
SKU_OFFER_OVERRIDES: dict[str, str] = {
    "freefire_cis-weekly-lite": "weekly_lite",
    "freefire_cis-weekly-membership": "weekly_membership",
    "freefire_cis-monthly-membership": "monthly_membership",
}
```

`_match_brand` consults it before the denomination logic, still writing through the same claims/collision pass so an override cannot double-claim an offer either.

- [ ] **Step 2: Switch the nine**

The seed writes `sku_sourcing_rules(mode='force_supplier', supplier_slug='nova')` for every SKU it mapped **in a brand listed in a new `SWITCH_TO_NOVA` set** (`{"free-fire"}` for now), upserting on `sku_id`. Print which SKUs were switched, separately from which were mapped: switching is what moves money, and it should be readable on its own line.

MLBB and PUBG are **not** in that set — their mappings stay a reserve, exactly as they are today.

- [ ] **Step 3: Dry-run, commit**

Run it against dev as far as the environment allows, then `git commit -m "chore(seed): route Free Fire CIS through NOVA"`.

---

## Task 4: The ten Free Fire items only NOVA sells

**Files:**

- Create: `scripts/seed/2026-09-18_free_fire_nova_only.py`
- Test: an integration case asserting the brand still resolves a player check (see Global Constraints)

- [ ] **Step 1: The product**

`free-fire-packs`, `kind='top_up'`, `sort_order=2`, active, translations `ru="Наборы"`, `en="Packs"`, `uz="Toʻplamlar"`, and `required_fields` **copied verbatim from `free-fire-diamonds`** — read it from the database in the same transaction rather than retyped, so it cannot drift:

```python
    fields = (await db.execute(
        select(Product.required_fields).join(Brand).where(
            Brand.slug == "free-fire", Product.slug == "free-fire-diamonds"
        )
    )).scalar_one()
```

- [ ] **Step 2: The SKUs**

Ten rows, `cost_usdt` from NOVA's live price, `price_usd = ceil(cost × 1.10, cents)`:

| sku_code                      | denomination        | product    | cost     | price |
| ----------------------------- | ------------------- | ---------- | -------- | ----- |
| `freefire_cis-newbie-bundle`  | Newbie Bundle       | packs      | 0.224400 | 0.25  |
| `freefire_cis-level-up-6`     | Level Up Package 6  | packs      | 0.293148 | 0.33  |
| `freefire_cis-level-up-10`    | Level Up Package 10 | packs      | 0.523362 | 0.58  |
| `freefire_cis-level-up-15`    | Level Up Package 15 | packs      | 0.523362 | 0.58  |
| `freefire_cis-level-up-20`    | Level Up Package 20 | packs      | 0.523362 | 0.58  |
| `freefire_cis-level-up-25`    | Level Up Package 25 | packs      | 0.523362 | 0.58  |
| `freefire_cis-level-up-30`    | Level Up Package 30 | packs      | 0.753678 | 0.83  |
| `freefire_cis-evo-access-3d`  | Evo Access 3d       | membership | 0.418710 | 0.47  |
| `freefire_cis-evo-access-7d`  | Evo Access 7d       | membership | 0.711858 | 0.79  |
| `freefire_cis-evo-access-30d` | Evo Access 30d      | membership | 2.093550 | 2.31  |

Each gets a `nova`/`game` mapping (`free_fire_cis` + the offer id from the spec's table) **and** a `force_supplier = nova` rule — without the rule they route to the manual queue, because auto sourcing skips a reserve and NOVA is their only mapping.

Fetch the live prices from NOVA in the script and **refuse to write** if a cost has moved more than 10 % from the table above: a price that moved that far is a catalogue change to look at, not a number to seed past.

- [ ] **Step 3: The regression test**

In the player-check integration suite: create a second active product under a brand whose first product declares a check, with the **same** `required_fields`, and assert `brand_check_field` still returns it. Then flip one field of the copy and assert it returns `None` and logs the mismatch — that is the trap this task walks past, and it should be a test rather than a comment.

- [ ] **Step 4: Commit**

---

## Task 5: Documentation

**Files:** `docs/decisions/0082-nova-steam-and-real-cost-basis.md`, `docs/runbooks/nova.md`, `apps/api/src/yupay/modules/orders/README.md` (if it documents margin), `docs/architecture/module-map.md` if a path changed.

- [ ] **Step 1: ADR-0082**

Four decisions: Steam through a sentinel mapping rather than a fourth `kind`; a recorded cost rather than a discount constant (their plan can change and a stale constant reports a margin nobody received); Free Fire switched wholesale rather than staged (the owner's call, with the cheapest-SKU rollback being one admin action); the ten NOVA-only SKUs needing an explicit rule as a direct consequence of ADR-0081's reserve rule.

- [ ] **Step 2: The runbook**

A Steam section: how to switch Steam to NOVA and back, that the amount sent is the face value while the charge is less, where the charge shows up (`supplier_charged_usd` on the task, `cost_usdt` on the line), and that the **first live Steam order through NOVA has never been placed** — with the same shape of check the games one got.

A Free Fire section: what is now routed to NOVA, what to do if their price moves above G2B's, and how to read the seed's two tables.

- [ ] **Step 3: `npx prettier --check .`, commit**

---

## Final gate

```bash
make lint typecheck test
npx prettier --check .
```

Then `superpowers:finishing-a-development-branch`.
