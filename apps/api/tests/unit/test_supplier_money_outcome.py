"""Whether a failed order kept our money — typed, total, per adapter.

M3b gives a reseller's deposit back automatically when a supplier refuses
**and returns our money**, and puts a human in the loop when it does not.
That decision is only ever as good as the fact underneath it, so this file
holds two different kinds of test:

- **the totality guard** — an AST walk over every module a registered
  fulfiller can return a result from, failing when any exit leaves the money
  question unanswered. It walks rather than lists for the reason
  ``test_outbound_ssrf.py`` walks ``__subclasses__`` rather than a literal
  set of leaves: the listed version of this test could not fail, because a
  new adapter would simply not be on the list.
- **the mappings themselves** — what each adapter answers, and on what
  evidence. They do not rest on the same kind of evidence and the tests say
  which is which: G-Engine reads an ``is_refunded`` field, Waxpeer keys on a
  status whose refund behaviour it has observed, G2B has a line in someone's
  documentation for almost everything — and, for exactly one rejection, their
  error string plus the owner's ruling of 2026-09-09 that it is not billed.
  That fourth kind is the weakest thing here that still pays a merchant out,
  so its tests are as much about what must **not** match as about what does.
"""

from __future__ import annotations

import ast
import inspect
import sys
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from typing import Any, cast, get_args

import pytest
from yupay.modules.fulfillment.suppliers import REGISTRY
from yupay.modules.fulfillment.suppliers.base import (
    FulfillerError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.g2b import LOW_BALANCE_ERROR, G2bFulfiller
from yupay.modules.fulfillment.suppliers.g2b_client import (
    G2bError,
    GameOrderCreated,
    VoucherPurchaseResult,
)
from yupay.modules.fulfillment.suppliers.gengine import PAY_REQUESTED_KEY, GEngineFulfiller
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineError,
    GEngineGiftOrder,
    GEngineOrder,
    GEngineShopOrder,
    GEngineUnavailableError,
)
from yupay.modules.fulfillment.suppliers.gengine_gifts import _map_gift_order
from yupay.modules.fulfillment.suppliers.waxpeer import (
    _money_for,
    _reconcile,
    _status_to_outcome,
)
from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerStatus, WaxpeerTopup
from yupay.modules.pricing.variable import UNITS_PER_USD

# No module-level ``asyncio`` mark: this file mixes sync and async tests, and
# ``asyncio_mode = "auto"`` already collects the async ones.
_PKG = "yupay.modules.fulfillment.suppliers"
#: ``_Reconciled`` is waxpeer's intermediate: it classifies there and both the
#: fulfil and the poll path re-wrap it, so a result type that stopped at the
#: two protocol types would not watch the one adapter owning both ``SPENT``
#: cells. The type is not the whole answer for it — see
#: ``test_waxpeers_mapping_is_total_by_construction``.
_RESULT_TYPES = frozenset({"FulfillResult", "FulfillStatus", "_Reconciled"})
_ERROR_TYPES = frozenset({"FulfillerError", "FulfillerNotIntegratedError"})


# ---------- the walk ----------


def _adapter_modules() -> dict[str, ModuleType]:
    """Every module a registered fulfiller can return a result from.

    Starts from :data:`REGISTRY` — so a supplier nobody registered is not
    this file's problem, and one somebody does register cannot escape it —
    then follows each adapter's own imports *within* the suppliers package.
    That second hop is not decoration: ``gengine.py`` delegates Steam gifts
    to ``gengine_gifts.py``, and a walk that stopped at the fulfiller class's
    own module would miss every terminal-failure exit in it.
    """
    found: dict[str, ModuleType] = {}
    queue: list[ModuleType | None] = [inspect.getmodule(type(f)) for f in REGISTRY.values()]
    while queue:
        mod = queue.pop()
        if mod is None or mod.__name__ in found or not mod.__name__.startswith(_PKG):
            continue
        found[mod.__name__] = mod
        for value in vars(mod).values():
            owner = getattr(value, "__module__", None)
            if isinstance(owner, str) and owner.startswith(_PKG):
                queue.append(sys.modules.get(owner))
    return found


def _calls(names: frozenset[str], tree: ast.Module, label: str) -> list[tuple[str, ast.Call]]:
    """Every call to one of ``names`` in ``tree``, tagged with where it is."""
    return [
        (f"{label}:{node.lineno}", node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names
    ]


def _adapter_calls(names: frozenset[str]) -> list[tuple[str, ast.Call]]:
    """The same, over every module the registry walk reaches."""
    out: list[tuple[str, ast.Call]] = []
    for mod_name, mod in sorted(_adapter_modules().items()):
        tree = ast.parse(inspect.getsource(mod))
        out += _calls(names, tree, f"{mod_name.rsplit('.', 1)[-1]}.py")
    return out


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_none(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _literal_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _result_offences(sites: list[tuple[str, ast.Call]]) -> list[str]:
    """Every construction of a result that does not answer the money question.

    Four rules, one per shape a construction site can take:

    - a terminal failure must name one of the three outcomes;
    - the low-balance stall must **not** — the order stays ``fulfilling`` and
      the money has not gone anywhere yet (M3b Task 4 owns it);
    - a success or an in-progress result must not claim a money outcome,
      because nothing terminal has happened to the money;
    - a pass-through (``outcome=result.outcome``) must pass the money outcome
      through too, or a real failure's answer is dropped in the re-wrap.
    """
    offences: list[str] = []
    for where, call in sites:
        money = _kw(call, "money_outcome")
        if money is None:
            offences.append(f"{where}: did not say what happened to our money")
            continue

        outcome = _literal_str(_kw(call, "outcome"))
        error = _kw(call, "error")
        is_stall = isinstance(error, ast.Name) and error.id == "LOW_BALANCE_ERROR"

        if outcome == "failed" and not is_stall:
            if _is_none(money):
                offences.append(f"{where}: a terminal failure must decide")
        elif outcome is not None:
            if not _is_none(money):
                offences.append(f"{where}: nothing terminal happened to the money here")
        elif _is_none(money):
            offences.append(f"{where}: a pass-through must pass the outcome through")
    return offences


def _raise_offences(sites: list[tuple[str, ast.Call]]) -> list[str]:
    """Every supplier error raised without answering the money question."""
    return [
        f"{where}: a raise is terminal and must say what happened to our money"
        for where, call in sites
        if (money := _kw(call, "money_outcome")) is None or _is_none(money)
    ]


def test_the_walk_reaches_the_delegate_modules_too() -> None:
    """A walk that found nothing would pass every test below vacuously.

    ``gengine_gifts`` is named because it is the one module the obvious
    version of this walk misses — it holds no ``Fulfiller`` class of its own,
    only the failure exits ``GEngineFulfiller`` returns from.
    """
    walked = {name.rsplit(".", 1)[-1] for name in _adapter_modules()}

    assert {"g2b", "gengine", "gengine_gifts", "waxpeer", "manual", "mock", "_stub"} <= walked


def test_every_result_says_what_happened_to_our_money() -> None:
    """No exit may leave the question unanswered, and none may fake an answer."""
    sites = _adapter_calls(_RESULT_TYPES)
    assert sites, "the walk found no results — the adapters moved"

    assert _result_offences(sites) == []


def test_every_raised_supplier_error_says_it_too() -> None:
    """A raise ends the task exactly as terminally as a ``failed`` result.

    ``process_task`` catches both supplier exceptions and marks the task
    ``failed``, so an adapter that raises has spent — or not spent — our
    money just as surely as one that returns. Leaving these out would have
    left the biggest hole in the whole mapping: every configuration and
    validation refusal, and every stub supplier, exits this way.
    """
    sites = _adapter_calls(_ERROR_TYPES)
    assert sites, "the walk found no supplier errors — the adapters moved"

    assert _raise_offences(sites) == []


_BAD_ADAPTER = """
def refuse(order, mapping):
    if order.dead:
        return FulfillResult(outcome="failed", error="dead", money_outcome=None)
    if order.shipped:
        return FulfillResult(outcome="succeeded", error=None, money_outcome=MoneyOutcome.RETURNED)
    if mapping is None:
        raise FulfillerError("no mapping")
    return FulfillStatus(outcome=other.outcome, error=other.error, money_outcome=None)
"""


def test_the_guard_above_actually_bites() -> None:
    """The rules, run against an adapter that breaks every one of them.

    Without this the two tests above would be indistinguishable from two that
    check nothing — which is the failure mode the walk exists to avoid, one
    level up. The snippet is parsed, never imported.
    """
    tree = ast.parse(_BAD_ADAPTER)

    results = _result_offences(_calls(_RESULT_TYPES, tree, "bad"))
    raises = _raise_offences(_calls(_ERROR_TYPES, tree, "bad"))

    # A set: ``ast.walk`` is breadth-first, so the order is the tree's, not
    # the file's.
    assert {o.split(": ", 1)[1] for o in results} == {
        "a terminal failure must decide",
        "nothing terminal happened to the money here",
        "a pass-through must pass the outcome through",
    }
    assert len(raises) == 1


# ---------- the shape of the answer ----------


def test_the_third_value_is_not_a_synonym_for_the_second() -> None:
    """Three values, and the strings they persist as.

    ``UNKNOWN`` is "we cannot tell"; ``SPENT`` is "we know it is gone".
    Collapsing them is the mistake M3a's ``attempt_delivered`` boolean made —
    it read "no" where the truth was "unknown", and a retry policy acted on
    it. Task 3 auto-refunds neither, but they say different things to a human.

    The values are pinned because they land in JSONB: renaming one silently
    turns every task already carrying it into "nothing recorded".
    """
    assert {m.value for m in MoneyOutcome} == {"returned", "spent", "unknown"}


def test_a_success_cannot_claim_a_money_outcome() -> None:
    """The invariant the AST walk checks statically, enforced at runtime too."""
    with pytest.raises(ValueError, match="money_outcome"):
        FulfillResult(
            outcome="succeeded",
            external_order_id="x",
            artifact_kind=None,
            artifact=None,
            error=None,
            extra_metadata={},
            money_outcome=MoneyOutcome.RETURNED,
        )
    with pytest.raises(ValueError, match="money_outcome"):
        FulfillStatus(
            outcome="in_progress",
            artifact_kind=None,
            artifact=None,
            error=None,
            money_outcome=MoneyOutcome.SPENT,
        )


# ---------- G-Engine: a field we read ----------


def _order(status: str, *, refunded: bool = False, order_id: int = 9001) -> GEngineOrder:
    return GEngineOrder(
        id=order_id, uuid="u-1", status=status, price=1.0, currency="USD", is_refunded=refunded
    )


class _PayRefused:
    async def pay_recharge_order(self, _order_id: int) -> GEngineOrder:
        raise GEngineError("g-engine HTTP 500", status=500, body="")


async def test_gengine_reads_the_refund_flag_it_already_records() -> None:
    """``is_refunded`` is a real field in their API — the strongest evidence
    any of the three adapters has, and it already drives the
    ``supplier_refunded`` metadata key."""
    f = GEngineFulfiller(cast(Any, object()))

    result = await f._advance(_order("cancelled", refunded=True), first_call=False)

    assert result.money_outcome is MoneyOutcome.RETURNED
    assert result.extra_metadata["supplier_refunded"] is True


async def test_gengine_a_rejected_player_never_cost_us_anything() -> None:
    """Their flow pays only a ``verified`` order, and this one never got
    there — so this is not "the supplier refunded us", it is "we never
    called pay". Our own call sequence, not their promise."""
    f = GEngineFulfiller(cast(Any, object()))

    result = await f._advance(_order("invalid_account"), first_call=False)

    assert result.money_outcome is MoneyOutcome.RETURNED
    assert result.extra_metadata["supplier_refunded"] is False


async def test_gengine_a_cancelled_order_with_no_refund_is_unknown_not_spent() -> None:
    """The flag says no refund landed. Nothing says the money left."""
    f = GEngineFulfiller(cast(Any, object()))

    result = await f._advance(_order("cancelled"), first_call=False)

    assert result.money_outcome is MoneyOutcome.UNKNOWN


async def test_gengine_a_refusal_mid_payment_is_unknown() -> None:
    """``GEngineError`` covers every status ≥ 400, a 500 included — so a
    refusal on the one call that spends cannot be read as "not charged"."""
    f = GEngineFulfiller(cast(Any, _PayRefused()))

    result = await f._advance(_order("verified"), first_call=False, paid_before=True)

    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.UNKNOWN


async def test_gengine_a_shop_order_cancelled_with_a_refund_returned_our_money() -> None:
    from yupay.modules.fulfillment.suppliers.gengine import _shop_result

    result = _shop_result(
        GEngineShopOrder(id=7, status="canceled", price=1.0, is_refunded=True, codes=[]),
        mapping=None,
        item=None,
    )

    assert result.money_outcome is MoneyOutcome.RETURNED
    assert result.extra_metadata["supplier_refunded"] is True


# ---------- G-Engine gifts: one call that both buys and pays ----------


def _gift(status: str, *, refunded: bool = False) -> GEngineGiftOrder:
    return GEngineGiftOrder(
        id=42,
        uuid="g-1",
        status=status,
        purchase_price=5.0,
        is_refunded=refunded,
        invite_url="https://s.team/p/abc",
        region="RU",
        package_id=11,
        package_name="Pack",
        error=None,
    )


def _task(**metadata: Any) -> Any:
    return SimpleNamespace(id="t-1", external_order_id=None, extra_metadata=metadata)


def test_a_refunded_gift_gave_our_money_back() -> None:
    status = _map_gift_order(_gift("canceled", refunded=True), task=_task())

    assert status.money_outcome is MoneyOutcome.RETURNED


def test_a_gift_cancelled_without_a_refund_is_unknown() -> None:
    status = _map_gift_order(_gift("canceled"), task=_task())

    assert status.money_outcome is MoneyOutcome.UNKNOWN


# ---------- Waxpeer: canceled and error are different money, and it says so ----------


def _topup(status: Any, *, give_units: int = 1000) -> WaxpeerTopup:
    return WaxpeerTopup(
        id=5,
        custom_id="c-1",
        status=status,
        amount_units=1000,
        give_amount_units=give_units,
        steam_login="player",
    )


def _line(price: str = "1.00") -> Any:
    return SimpleNamespace(id="i-1", sku_id="s-1", qty=1, unit_price_usd=Decimal(price))


def test_waxpeer_canceled_put_the_money_back_on_our_balance() -> None:
    reconciled = _reconcile(item=_line(), topup=_topup("canceled"))

    assert reconciled.money_outcome is MoneyOutcome.RETURNED
    assert reconciled.extra_metadata["supplier_refunded"] is True


def test_waxpeer_error_is_the_one_case_we_know_the_money_is_gone() -> None:
    """Waxpeer does not auto-refund an ``error`` — the adapter has said so in
    its own words since the integration landed. That is a positive fact, not
    an absence of one, which is what separates ``SPENT`` from ``UNKNOWN``."""
    reconciled = _reconcile(item=_line(), topup=_topup("error"))

    assert reconciled.money_outcome is MoneyOutcome.SPENT
    assert reconciled.extra_metadata["needs_reconciliation"] is True


def test_waxpeer_an_under_delivery_spent_the_money_it_short_changed_us_on() -> None:
    """The top-up landed, for less than we promised. Nothing is coming back."""
    reconciled = _reconcile(
        item=_line("1.00"), topup=_topup("completed", give_units=UNITS_PER_USD // 2)
    )

    assert reconciled.outcome == "failed"
    assert reconciled.money_outcome is MoneyOutcome.SPENT


def test_waxpeer_a_delivered_top_up_claims_nothing_about_the_money() -> None:
    reconciled = _reconcile(item=_line(), topup=_topup("completed"))

    assert reconciled.outcome == "succeeded"
    assert reconciled.money_outcome is None


def test_waxpeers_mapping_is_total_by_construction() -> None:
    """Every status Waxpeer can report, walked off the client's own Literal.

    The AST guard cannot reach this: waxpeer classifies inside ``_reconcile``
    and hands the answer to ``_Reconciled(money_outcome=...)`` as a name, which
    is not a literal ``None`` and so satisfies the guard whatever the name
    holds. The hole that shape used to have was a seeded ``money = None`` that
    a forgetful branch would leave untouched; ``_money_for`` has no seed, so
    mypy's return checking closes it — and this walks the status set to prove
    the mapping covers it, rather than listing the statuses somebody thought
    of.
    """
    statuses = get_args(WaxpeerStatus)
    assert statuses, "the client's status Literal moved"

    for status in statuses:
        terminal = _status_to_outcome(status) == "failed"
        answer = _money_for(
            outcome="failed" if terminal else "in_progress", status=status, shortfall=0
        )
        assert (answer is not None) is terminal, f"{status}: totality"

    # And the under-delivery, which is terminal without a terminal status.
    assert _money_for(outcome="failed", status="completed", shortfall=1) is MoneyOutcome.SPENT


# ---------- G2B: a promise, plus one rejection the owner graded ----------


class _G2bFake:
    def __init__(self, **canned: Any) -> None:
        self._canned = canned

    def _resolve(self, name: str) -> Any:
        value = self._canned[name]
        if isinstance(value, Exception):
            raise value
        return value

    async def get_me(self) -> dict[str, Any]:
        return {"balance": "1000"}

    async def purchase_voucher(self, **_kw: Any) -> VoucherPurchaseResult:
        return cast(VoucherPurchaseResult, self._resolve("purchase_voucher"))

    async def create_game_order(self, **_kw: Any) -> GameOrderCreated:
        return cast(GameOrderCreated, self._resolve("create_game_order"))


def _mapping(kind: str) -> Any:
    return SimpleNamespace(
        kind=kind, external_product_id="EP-1", external_variant_id="VAR-1", quantity=1
    )


def _g2b_item() -> Any:
    return SimpleNamespace(
        id="item-123456789abc",
        sku_id="sku-1",
        qty=1,
        fulfillment_data={"player_id": "777"},
        sku=None,  # no cost data → the balance pre-flight is skipped
    )


async def test_g2b_cannot_do_better_than_unknown() -> None:
    """G2B publishes no refund field. Their documentation says a FAILED order
    auto-refunds the balance, and that is the whole of the evidence — a
    promise we have never checked against anything we read. ``RETURNED``
    here would spend a merchant's deposit on someone else's paperwork, so
    the third value exists for exactly this.

    The one rejection M3c graded does not reach this path: it is a *raise*
    from the game create, not a ``failed`` status on a call that succeeded."""
    f = G2bFulfiller(
        client=cast(
            Any,
            _G2bFake(
                purchase_voucher=VoucherPurchaseResult(
                    g2b_order_id="G-1", status="failed", delivery_items=None
                )
            ),
        )
    )

    result = await f._fulfill_voucher(
        mapping=_mapping("voucher"), item=_g2b_item(), idempotency_key="k-1"
    )

    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.UNKNOWN


async def test_g2b_a_failed_game_order_is_unknown_for_the_same_reason() -> None:
    f = G2bFulfiller(
        client=cast(
            Any, _G2bFake(create_game_order=GameOrderCreated(g2b_order_id="G-2", status="failed"))
        )
    )

    result = await f._fulfill_game(
        mapping=_mapping("game"), item=_g2b_item(), idempotency_key="k-2"
    )

    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.UNKNOWN


#: The exact body G2B answered a real merchant game create with on
#: 2026-09-09 (order ``m3b-parkA-1``). The owner ruled the same day that G2B
#: does not debit us for it.
_LIVE_INVALID_PLAYER_BODY = (
    '{"message":"Invalid player ID. Please check and try again.","success":false}'
)


async def _game_create_raising(exc: Exception) -> FulfillResult:
    f = G2bFulfiller(client=cast(Any, _G2bFake(create_game_order=exc)))
    return await f._fulfill_game(
        mapping=_mapping("game"), item=_g2b_item(), idempotency_key="k-invalid"
    )


async def test_g2b_an_invalid_player_id_is_money_we_never_spent() -> None:
    """A fourth kind of evidence, and the weakest that still pays out:
    G2B's own rejection string, plus the owner's knowledge (2026-09-09) that
    their balance is not debited for it. Not a field we read, not a promise in
    a document — an observed refusal we have been told is free."""
    with pytest.raises(FulfillerError) as caught:
        await _game_create_raising(G2bError(400, _LIVE_INVALID_PLAYER_BODY))

    assert caught.value.money_outcome is MoneyOutcome.RETURNED


@pytest.mark.parametrize(
    ("status", "body"),
    [
        pytest.param(
            400,
            '{"message":"Catalogue item not found.","success":false}',
            id="another-400",
        ),
        pytest.param(500, _LIVE_INVALID_PLAYER_BODY, id="a-500"),
    ],
)
async def test_g2b_a_rejection_we_do_not_recognise_is_still_unknown(status: int, body: str) -> None:
    """The fallback is the design. Only the one shape above is graded; every
    other refusal from a call that went out keeps answering ``UNKNOWN`` and
    keeps fetching a human."""
    with pytest.raises(FulfillerError) as caught:
        await _game_create_raising(G2bError(status, body))

    assert caught.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_g2b_the_low_balance_branch_still_wins_a_body_that_matches_both() -> None:
    """Order of the two matchers, on a body both would claim. Low balance is
    checked first and is **not** terminal: the order stays in flight, an admin
    tops the supplier up, and no money outcome is recorded at all — which is
    the one answer that leaves every later verdict open."""
    # Both matchers must actually accept this body, or the test grades
    # nothing. ``_looks_like_low_balance`` searches the **whole** body for its
    # hints, so the extra field carries "balance" while the message stays the
    # observed string byte-for-byte — which is what whole-message equality
    # requires. (A body reading "Invalid player ID. Insufficient balance."
    # would satisfy only the loose matcher, and this test would pass while
    # proving no precedence at all.)
    result = await _game_create_raising(
        G2bError(
            400,
            '{"message":"Invalid player ID. Please check and try again.",'
            '"success":false,"balance":"0.00"}',
        )
    )

    assert result.outcome == "failed"
    assert result.error == LOW_BALANCE_ERROR
    assert result.money_outcome is None


def test_the_unbilled_player_rejection_is_consulted_at_exactly_one_site() -> None:
    """The owner's ruling covers a **game create**, and nothing else.

    The voucher branch never sends a player id, so a voucher rejection
    carrying that message would be evidence of nothing — and copying the
    ternary onto ``_fulfill_voucher``'s raise is a two-line edit that no other
    test would notice. This walks every adapter module the registry reaches
    and pins the call count, because the paragraph forbidding it lives two
    hundred lines from where it would be broken.
    """
    sites = [where for where, _ in _adapter_calls(frozenset({"_is_an_unbilled_player_rejection"}))]

    # The file, not the line: a line number churns on every edit above it and
    # says nothing about the rule. One call, in the g2b adapter, is the rule.
    assert [w.split(":")[0] for w in sites] == ["g2b.py"], (
        "the unbilled-player predicate is consulted somewhere new. It grades one "
        "rejection of one call — the g2b game create — on the owner's 2026-09-09 "
        f"ruling, which covers nothing else. Sites: {sites}"
    )


# ---------- the stall is Task 4's, and stays unclassified ----------


async def test_a_low_balance_refusal_is_not_classified_at_all() -> None:
    """It is not terminal: the order stays ``fulfilling`` and an admin tops
    up. Giving it a money outcome would invite Task 3 to act on an order
    that has not finished failing."""
    from yupay.modules.fulfillment.suppliers.g2b import _low_balance_result

    result = _low_balance_result(
        mapping=_mapping("voucher"),
        kind="voucher",
        current_balance=Decimal("1"),
        required=Decimal("9"),
        source="test",
    )

    assert result.outcome == "failed"
    assert result.money_outcome is None


# ---------- our own warehouse, and suppliers that were never wired up ----------


async def test_a_stub_supplier_cannot_have_spent_anything() -> None:
    """It has no upstream to spend at. A stub's failure that read ``SPENT``
    or ``UNKNOWN`` would park a human on an order nobody ever billed."""
    from yupay.modules.fulfillment.suppliers.base import FulfillerNotIntegratedError

    stub = REGISTRY["steam"]
    with pytest.raises(FulfillerNotIntegratedError) as caught:
        await stub.fulfill(
            db=cast(Any, None), order=cast(Any, None), item=cast(Any, None), idempotency_key="k"
        )

    assert caught.value.money_outcome is MoneyOutcome.RETURNED


# ---------- and it survives onto the task ----------


def test_the_task_carries_the_typed_value_and_gives_it_back() -> None:
    """The fact is persisted where Task 3 will read it, and read back typed.

    ``extra_metadata`` is JSONB, so what lands there is the member's string
    value; ``money_outcome_of`` is the only supported way back, and a value
    it does not recognise reads as "nothing recorded" rather than crashing a
    saga on a row an older or newer deploy wrote.
    """
    # Both are needed only so SQLAlchemy can configure the mappers ``Order``
    # and ``OrderItem`` point at; ``service`` imports them lazily, inside the
    # saga, so importing it is not enough on its own.
    from yupay.modules.catalog.models import Sku  # noqa: F401
    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.fulfillment.service import money_outcome_of, record_money_outcome
    from yupay.modules.payments.models import Payment  # noqa: F401

    task = FulfillmentTask(id="t-1", supplier="g2b", status="failed", extra_metadata={"a": 1})

    assert money_outcome_of(task) is None

    record_money_outcome(task, MoneyOutcome.RETURNED)

    assert task.extra_metadata["money_outcome"] == "returned"
    assert task.extra_metadata["a"] == 1, "the merge must not drop supplier metadata"
    assert money_outcome_of(task) is MoneyOutcome.RETURNED

    task.extra_metadata = {**task.extra_metadata, "money_outcome": "reimbursed-ish"}
    assert money_outcome_of(task) is None


def test_our_own_warehouse_running_dry_spent_nothing() -> None:
    """No supplier is involved in an inventory route at all, so a no-stock
    failure is the cleanest ``RETURNED`` in the codebase — and the one case
    where an automatic refund is unambiguously right."""
    from yupay.modules.fulfillment.service import INVENTORY_FAILURE_MONEY_OUTCOME

    assert INVENTORY_FAILURE_MONEY_OUTCOME is MoneyOutcome.RETURNED


def test_a_later_attempt_cannot_declare_the_money_whole_again() -> None:
    """The one rule that keeps ``RETURNED`` safe on a row that outlives it.

    Every ``RETURNED`` an adapter can produce is a fact about **one attempt**.
    A task is retried, and the replay knows nothing about what the attempt
    before it spent — so a charge that lands and then 500s (``UNKNOWN``,
    correctly), followed by the ordinary admin Retry and a transient outage
    before anything is created (``RETURNED``, also correctly), used to end as a
    task claiming we still had the money. Task 3 would have refunded a deposit
    for goods already paid for.
    """
    from yupay.modules.catalog.models import Sku  # noqa: F401
    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.fulfillment.service import money_outcome_of, record_money_outcome
    from yupay.modules.payments.models import Payment  # noqa: F401

    task = FulfillmentTask(id="t-2", supplier="gengine", status="failed", extra_metadata={})

    record_money_outcome(task, MoneyOutcome.UNKNOWN)  # the charge that may have landed
    record_money_outcome(task, MoneyOutcome.RETURNED)  # the replay that saw nothing

    assert money_outcome_of(task) is MoneyOutcome.UNKNOWN


def test_but_new_bad_news_still_lands() -> None:
    """Upward is open: learning money *is* gone is new knowledge, not an older
    attempt's absence of it."""
    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.fulfillment.service import money_outcome_of, record_money_outcome

    task = FulfillmentTask(id="t-3", supplier="waxpeer", status="failed", extra_metadata={})

    record_money_outcome(task, MoneyOutcome.RETURNED)
    record_money_outcome(task, MoneyOutcome.UNKNOWN)
    assert money_outcome_of(task) is MoneyOutcome.UNKNOWN

    record_money_outcome(task, MoneyOutcome.SPENT)
    assert money_outcome_of(task) is MoneyOutcome.SPENT


def test_knowing_it_is_gone_is_not_forgotten_either() -> None:
    """Waxpeer says ``error`` — we know the money is gone. An admin retries,
    the create fails ambiguously, and the adapter answers ``UNKNOWN`` for that
    attempt. The inbox must not start saying "we cannot tell" about money we
    knew was spent: Task 3 treats the two the same, but a human does not, and
    blurring them is what ``MoneyOutcome``'s own docstring forbids."""
    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.fulfillment.service import money_outcome_of, record_money_outcome

    task = FulfillmentTask(id="t-5", supplier="waxpeer", status="failed", extra_metadata={})

    record_money_outcome(task, MoneyOutcome.SPENT)
    record_money_outcome(task, MoneyOutcome.UNKNOWN)

    assert money_outcome_of(task) is MoneyOutcome.SPENT


def test_a_value_we_cannot_parse_still_blocks_a_promotion() -> None:
    """The ladder fails **closed**, because the only re-grade is a DB edit.

    ``money_outcome_of`` reads an unrecognised string as "nothing recorded" —
    right for a reader, wrong for the guard. The enum's values are lowercase,
    so an operator hand-editing a row to ``'UNKNOWN'`` would otherwise disarm
    the invariant on exactly the task a human was already worried about, and a
    later replay would promote it to ``RETURNED``.
    """
    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.fulfillment.service import money_outcome_of, record_money_outcome

    task = FulfillmentTask(
        id="t-6",
        supplier="gengine",
        status="failed",
        extra_metadata={"money_outcome": "UNKNOWN"},  # an operator's shouting
    )

    assert money_outcome_of(task) is None, "a reader still sees nothing recorded"

    record_money_outcome(task, MoneyOutcome.RETURNED)

    assert money_outcome_of(task) is None, "and the promotion was refused"

    record_money_outcome(task, MoneyOutcome.SPENT)

    assert money_outcome_of(task) is MoneyOutcome.SPENT, "real knowledge still lands"


def test_a_repeated_returned_is_not_treated_as_a_promotion() -> None:
    """Two attempts that both spent nothing leave a task that spent nothing."""
    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.fulfillment.service import money_outcome_of, record_money_outcome

    task = FulfillmentTask(id="t-4", supplier="inventory", status="failed", extra_metadata={})

    record_money_outcome(task, MoneyOutcome.RETURNED)
    record_money_outcome(task, MoneyOutcome.RETURNED)

    assert money_outcome_of(task) is MoneyOutcome.RETURNED


def test_a_gengine_customer_fault_after_we_tried_to_pay_is_not_free() -> None:
    """The ``RETURNED`` cell for a rejected player is *checked*, not inferred.

    Their documented flow verifies before it pays, and a mapping that trusted
    that sentence would rest on the same evidence class this package refuses to
    act on for G2B. So the adapter carries whether a pay request has gone out,
    and only a "no" earns ``RETURNED``.
    """
    from yupay.modules.fulfillment.suppliers.gengine import _failed

    unpaid = _failed(_order("invalid_account"), "invalid_account", pay_may_have_landed=False)
    tried = _failed(_order("invalid_account"), "invalid_account", pay_may_have_landed=True)

    assert unpaid.money_outcome is MoneyOutcome.RETURNED
    assert tried.money_outcome is MoneyOutcome.UNKNOWN


class _PaidThenPending:
    """A client whose pay call succeeds and leaves the order ``processing``."""

    def __init__(self) -> None:
        self.pay_calls = 0

    async def pay_recharge_order(self, order_id: int) -> GEngineOrder:
        self.pay_calls += 1
        return _order("processing", order_id=order_id)


async def test_nothing_is_spent_until_the_intent_is_committed() -> None:
    """The ordering the whole mechanism rests on.

    A pay that returns 200 leaves the order ``processing`` — ``in_progress``,
    which records **no money outcome at all**. So the record of the spend
    cannot live in the transaction that spends: an abort anywhere after the
    pay (the metadata merge, ``_try_settle_order``'s blocking lock, the COMMIT,
    and the poll path has no crash net) would roll the record back while the
    money stayed gone, and the next poll seeing ``invalid_account`` would
    answer ``RETURNED`` for a top-up we bought.

    So a ``verified`` order is not paid until a *previous*, non-paying tick has
    committed the intent.
    """
    client = _PaidThenPending()
    f = GEngineFulfiller(cast(Any, client))

    banked = await f._advance(_order("verified"), first_call=False)

    assert client.pay_calls == 0, "the tick that records the intent spends nothing"
    assert banked.outcome == "in_progress"
    assert banked.money_outcome is None, "nothing terminal happened yet"
    assert banked.extra_metadata[PAY_REQUESTED_KEY] is True

    paid = await f._advance(_order("verified"), first_call=False, paid_before=True)

    assert client.pay_calls == 1
    assert paid.outcome == "in_progress"
    assert paid.extra_metadata[PAY_REQUESTED_KEY] is True, "and it stays on the task"

    # The poll after that, with the supplier now claiming a bad account.
    later = await f._advance(_order("invalid_account"), first_call=False, paid_before=True)

    assert later.outcome == "failed"
    assert later.money_outcome is MoneyOutcome.UNKNOWN


async def test_a_lost_pay_response_is_remembered_the_same_way() -> None:
    """The other branch: we never learned whether the charge landed. The
    intent was already committed a tick earlier, so it survives regardless."""

    class _PayUnavailable:
        async def pay_recharge_order(self, _order_id: int) -> GEngineOrder:
            raise GEngineUnavailableError("timeout")

    f = GEngineFulfiller(cast(Any, _PayUnavailable()))

    undecided = await f._advance(_order("verified"), first_call=False, paid_before=True)

    assert undecided.outcome == "in_progress"
    assert undecided.extra_metadata[PAY_REQUESTED_KEY] is True


async def test_check_status_hands_the_breadcrumb_back_to_the_state_machine() -> None:
    """The wiring, not just the two halves: ``check_status`` is the only place
    that can read the task, and a poll that dropped the key would put the hole
    straight back."""

    class _Fetches:
        async def get_recharge_order(self, _order_id: int) -> GEngineOrder:
            return _order("invalid_account")

    f = GEngineFulfiller(cast(Any, _Fetches()))
    task = SimpleNamespace(
        id="t-9",
        external_order_id="9001",
        extra_metadata={"supplier": "gengine", PAY_REQUESTED_KEY: True},
    )

    status = await f.check_status(db=cast(Any, None), task=cast(Any, task))

    assert status.outcome == "failed"
    assert status.money_outcome is MoneyOutcome.UNKNOWN


async def test_a_refund_field_still_wins_over_the_breadcrumb() -> None:
    """``is_refunded`` is an observation about the money itself: it outranks a
    record of what was spent to send it. Demoting here would have been the
    same over-reach as demoting waxpeer's ``canceled``."""
    f = GEngineFulfiller(cast(Any, object()))

    result = await f._advance(
        _order("cancelled", refunded=True), first_call=False, paid_before=True
    )

    assert result.money_outcome is MoneyOutcome.RETURNED
