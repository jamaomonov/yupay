#!/usr/bin/env python
"""Mutation harness for the automatic deposit refund (M3b, Tasks 3 and 5).

Task 5 added four rows for the **merchant's quote** (`order_items.
merchant_expected_price_usd`, migration 0072). They are here rather than in a
harness of their own because they belong to the same record: what a reseller
quoted is what a charge dispute is settled from, and it is written on the order
line whose price the refund's amount is deliberately *not* read from. Their
mutations are the two ways to lose the write and the two guards that keep the
column's NULL meaningful.

Same contract as its three siblings: break one property at a time and check
that the named test actually goes red. A test that stays green under a
mutation is a test that would not have noticed the regression, and on this
branch six such tests have already been found by review — two of them by an
implementer running one of these harnesses on their own work.

This one covers the money path, so its rows are chosen for what each one
would cost in production rather than for line coverage: two of them
(``retry_after_a_refund``, ``already_settled_check``) are worth a merchant's
whole order value each, and ``refund_inside_the_savepoint`` is worth every
future refund on the affected task, because the value it corrupts
(``money_outcome = unknown``) has no operator path back.

The runner, the guarantees it enforces and the rules for running one live in
:mod:`_falsify`; read that first. Run it::

    uv run python apps/api/tests/tools/falsify_merchant_refund.py
    uv run python apps/api/tests/tools/falsify_merchant_refund.py -k gate
    uv run python apps/api/tests/tools/falsify_merchant_refund.py --check-anchors

## Two properties are deliberately not falsifiable here, and one that stopped being one

**"A frozen merchant is still refunded"** has no code to delete — the refund
simply never reads ``merchants.status``. Its mutation therefore *adds* the
check somebody would plausibly add, which is the only honest way to falsify an
absence.

**The concurrent-drain interleave** (``test_two_drainers_on_two_connections_refund_once``)
is guarded by a Postgres unique index, not by any line in this repo. Removing
``wallet.service.post``'s IntegrityError arm would break a hundred unrelated
tests and prove nothing about this one; the test earns its place by using two
real connections rather than by a row here.

**Nothing.** The third absence this file used to declare — the seam's
placement — is gone, and the way it went is the lesson. Fix round 1 claimed
placement could not be falsified because it would need a fault in
``_load_task``, which the whole saga shares. That was wrong twice: a
**caller-scoped** fault is about ten lines (see
``test_a_fault_in_the_seams_own_reads_is_reported_not_fatal``), and the
property placement was protecting had in the meantime moved. Fix round 2 made
the seam's whole body exception-safe, which left exactly one statement outside
— the flush of the caller's own writes — and that is now what
``refund_inside_the_savepoint`` grades. A declared absence is honest only
while its stated reason is true; re-derive it whenever the code under it
moves.
"""

from __future__ import annotations

import sys

from _falsify import SRC, Mutation, main

LIVE = "apps/api/tests/integration/test_merchant_auto_refund.py"
KEYS = "apps/api/tests/unit/test_merchant_refund_keys.py"
ATTRIB = "apps/api/tests/integration/test_merchant_deposit_attribution.py"
#: Task 5's quote record. Not a refund, but the same money record: what a
#: reseller quoted is what a charge dispute is settled from, and it is written
#: on the order line the refund's amount is deliberately *not* read from.
PLACE = "apps/api/tests/integration/test_merchant_api_orders.py"
ACTOR = "apps/api/tests/integration/test_orders_merchant_actor.py"

G2B_UNIT = "apps/api/tests/unit/test_g2b_fulfiller.py"
#: Where the mappings themselves are graded, adapter by adapter.
OUTCOME = "apps/api/tests/unit/test_supplier_money_outcome.py"

REFUND = SRC / "modules/merchants/refund.py"
DEPOSIT = SRC / "modules/merchants/deposit.py"
STATUS = SRC / "modules/merchants/order_status.py"
SAGA = SRC / "modules/fulfillment/service.py"
PLACEMENT = SRC / "modules/merchants/orders.py"
ORDERS = SRC / "modules/orders/service.py"
G2B = SRC / "modules/fulfillment/suppliers/g2b.py"


MUTATIONS: tuple[Mutation, ...] = (
    # ---- what may fire a refund at all
    Mutation(
        name="refund_on_any_outcome",
        breaks="money we never got back is refunded on a guess",
        edits=((SAGA, "    if outcome is not MoneyOutcome.RETURNED:", "    if False:"),),
        tests=(LIVE,),
        expect=(
            "test_a_failure_that_did_not_return_our_money_refunds_nothing[spent]",
            "test_a_failure_that_did_not_return_our_money_refunds_nothing[unknown]",
            "test_a_g2b_rejection_we_do_not_recognise_still_parks_the_merchant_order",
            "test_a_manually_failed_merchant_order_reaches_the_seam",
        ),
    ),
    Mutation(
        name="no_merchant_gate",
        breaks="every retail order that runs the warehouse dry reaches the refund",
        edits=(
            (
                SAGA,
                "    return row if row is not None and row.merchant_id is not None else None",
                "    return row",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_retail_failure_never_reaches_the_refund_at_all",
            "test_the_same_g2b_rejection_moves_no_money_for_a_retail_order",
        ),
    ),
    Mutation(
        name="frozen_blocks_the_refund",
        breaks="an account under review stops being owed for goods we failed to deliver",
        edits=(
            (
                REFUND,
                "    key = refund_key(order_id)",
                "    from yupay.modules.merchants.service import get_merchant\n\n"
                '    if (await get_merchant(db, merchant_id)).status != "active":\n'
                '        raise NotAMerchantOrderError("frozen")\n'
                "    key = refund_key(order_id)",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_frozen_merchant_is_still_refunded",),
    ),
    # ---- where the seam runs. The expensive one.
    Mutation(
        # The placement half, **alone**. Fix round 2 made the seam's whole body
        # exception-safe, so moving the call inside the savepoint no longer
        # changes anything the seam itself does. One statement is deliberately
        # left outside both the try and the savepoint — the flush of the
        # *caller's* writes, which a savepoint cannot contain without
        # discarding the failure record the refund acts on — and that is the
        # whole of what placement still protects. Its test is the one below.
        name="refund_inside_the_savepoint",
        breaks="a failure to persist the caller's writes is stamped UNKNOWN by the crash arm",
        edits=(
            (
                SAGA,
                "                failed = (await process_task(db, task_id=task_id)).status"
                ' == "failed"\n',
                "                failed = (await process_task(db, task_id=task_id)).status"
                ' == "failed"\n'
                "                if failed:\n"
                "                    await _settle_merchant_deposit(db, task_id=task_id)\n",
            ),
            (
                SAGA,
                "            await _settle_merchant_deposit(db, task_id=task_id)\n"
                "        settled.add(order_id)",
                "            pass\n        settled.add(order_id)",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_failure_to_persist_the_callers_writes_is_not_turned_into_unknown",),
    ),
    Mutation(
        # `a_seam_read_outside_the_catch` below grades a read **inside** the
        # try and stayed green while this one was broken. The two placements
        # are different properties and now have different rows: that one says
        # the seam's own reads are covered, this one says the gate read is too.
        # "Ahead of the savepoint" and "ahead of the try" are not the same
        # move, and a loose instruction to make the first produced the second.
        name="merchant_gate_outside_the_catch",
        breaks="a fault in the gate read escapes the drain with no line and no alert",
        edits=(
            (
                SAGA,
                "    try:\n"
                "        row = await _merchant_of_task(db, task_id)\n"
                "        if row is None:\n"
                "            return\n"
                '        seen["order_id"] = row.id\n',
                "    row = await _merchant_of_task(db, task_id)\n"
                "    if row is None:\n"
                "        return\n"
                '    seen["order_id"] = row.id\n'
                "    try:\n",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_fault_in_the_merchant_gate_is_reported_not_fatal",),
    ),
    Mutation(
        # Fix round 1's shape, restored: one of the seam's own reads back
        # outside the try. It propagates with no log line and no alert, and
        # the queue re-crashes on it every tick.
        name="a_seam_read_outside_the_catch",
        breaks="a fault in the seam's own reads takes the shared queue down, silently",
        edits=(
            (
                SAGA,
                "    seen: dict[str, str] = {}\n    try:",
                "    seen: dict[str, str] = {}\n    await _load_task(db, task_id)\n    try:",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_fault_in_the_seams_own_reads_is_reported_not_fatal",),
    ),
    Mutation(
        # The one case every document on this path cites as the reason for
        # catching, and the one fix round 2's catch did not cover.
        name="handler_imports_what_it_is_reporting_about",
        breaks="an unimportable refund module escapes from the handler that exists to report it",
        edits=(
            (
                SAGA,
                '    module = sys.modules.get("yupay.modules.merchants.refund")\n'
                '    refund_error = getattr(module, "RefundError", None)\n'
                "    if isinstance(refund_error, type) and issubclass(refund_error, BaseException):\n"
                "        return isinstance(exc, refund_error | AppError | SQLAlchemyError)\n"
                "    return isinstance(exc, AppError | SQLAlchemyError)",
                "    from yupay.modules.merchants.refund import RefundError\n\n"
                "    return isinstance(exc, RefundError | AppError | SQLAlchemyError)",
            ),
        ),
        tests=(LIVE,),
        expect=("test_an_unimportable_refund_module_is_reported_not_fatal",),
    ),
    Mutation(
        name="the_reporter_can_take_the_queue_down",
        breaks="a raise while reporting a failure stalls the drain instead of degrading",
        edits=(
            (
                SAGA,
                "        except Exception:  # noqa: BLE001 -- nothing may escape the reporter",
                "        except ValueError:  # noqa: BLE001 -- nothing may escape the reporter",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_crash_while_reporting_a_crash_still_does_not_stall_the_queue",),
    ),
    Mutation(
        name="cancel_gate_reads_a_sum_as_a_flag",
        breaks="one cent silences the cancellation alert while the rest sits parked",
        edits=(
            (
                SAGA,
                "        if not await merchant_refund.is_settled_in_full(",
                "        if not await merchant_refund.returned_for_order(",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_penny_does_not_silence_the_cancellation_alert",),
    ),
    Mutation(
        name="cancel_alert_on_the_happy_path",
        breaks="the one alert I3 exists for fires on every settled order, and ops stops reading it",
        edits=(
            (
                SAGA,
                "        if not await merchant_refund.is_settled_in_full(\n"
                "            db, merchant_id=merchant_id, order_id=task.order_id\n"
                "        ):",
                "        if True:",
            ),
        ),
        tests=(LIVE,),
        expect=("test_cancelling_an_already_refunded_order_says_nothing",),
    ),
    Mutation(
        name="stall_refunded_on_an_earlier_verdict",
        breaks="a low-balance stall is refunded on the previous attempt's RETURNED",
        edits=(
            (
                SAGA,
                "    item = (\n"
                "        await db.execute(select(OrderItem).where(OrderItem.id == task.order_item_id))\n"
                "    ).scalar_one()\n"
                '    if item.fulfillment_state != "failed":\n'
                "        return\n",
                "",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_low_balance_stall_is_not_refunded_on_an_earlier_verdict",),
    ),
    Mutation(
        name="seam_propagates_and_livelocks_the_queue",
        breaks="one crashing refund rolls back the batch and re-crashes every tick",
        edits=(
            (
                SAGA,
                "        try:\n            # ``_crash_detail``, not ``str(exc)``",
                # A **behavioural** narrowing, because a syntactic one cannot
                # compile here: the lazy import moved into the body, so
                # ``RefundError`` is not a name in this scope and a module-scope
                # import would close the very cycle the laziness exists for.
                # The first attempt at this row named ``merchant_refund``
                # anyway — it raised ``NameError``, leaving the mutant with **no
                # catch at all** rather than a narrow one, reddening nine tests
                # where a real narrowing reds four. The anchor still matched, so
                # ``SystemExit`` could not see it.
                "        if not _is_modelled(exc):\n"
                "            raise\n"
                "        try:\n"
                "            # ``_crash_detail``, not ``str(exc)``",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_crashing_refund_does_not_take_the_rest_of_the_batch_down",
            "test_a_fault_in_the_merchant_gate_is_reported_not_fatal",
            "test_a_fault_in_the_seams_own_reads_is_reported_not_fatal",
            "test_an_unexpected_refund_crash_never_reaches_the_unknown_crash_arm",
            "test_an_unimportable_refund_module_is_reported_not_fatal",
        ),
    ),
    Mutation(
        name="partial_settlement_claims_a_full_refund",
        breaks="one cent back reads as 'nothing to chase, refund your customer'",
        edits=(
            (
                STATUS,
                "        whole = refund.settled_in_full(charged=charged, returned=refunded)",
                "        whole = refunded > 0",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_partial_settlement_does_not_claim_the_order_was_refunded",),
    ),
    Mutation(
        name="manual_rejection_skips_the_seam",
        breaks="the fourth terminal site parks a deposit with nobody told",
        edits=(
            (
                SAGA,
                "    await _settle_merchant_deposit(db, task_id=task_id)\n    return task",
                "    return task",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_manually_failed_merchant_order_reaches_the_seam",),
    ),
    Mutation(
        name="cancellation_is_silent",
        breaks="a cancelled merchant task leaves a debited deposit nobody can find",
        edits=(
            (
                SAGA,
                "            _dispatch_alert(\n"
                "                _alert_merchant_order_cancelled(\n"
                "                    task_id=task.id, order_id=task.order_id, reason=reason\n"
                "                )\n"
                "            )\n",
                "",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_penny_does_not_silence_the_cancellation_alert",
            "test_cancelling_a_merchant_task_says_the_deposit_is_parked",
        ),
    ),
    # ---- the amount
    Mutation(
        name="amount_from_the_order_line",
        breaks="the refund follows the order line instead of what we charged",
        edits=(
            (
                DEPOSIT,
                "from yupay.modules.orders.models import Order\n",
                "from yupay.modules.orders.models import Order, OrderItem\n",
            ),
            (
                DEPOSIT,
                "    total = (await db.execute(stmt)).scalar_one_or_none()\n"
                "    return None if total is None else Decimal(total)",
                "    total = (\n"
                "        await db.execute(\n"
                "            select(OrderItem.unit_price_usd).where(OrderItem.order_id == order_id)\n"
                "        )\n"
                "    ).scalar_one_or_none()\n"
                "    return None if total is None else Decimal(total)",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_an_order_with_no_charge_refunds_nothing_and_calls_a_human",
            "test_the_refund_is_what_we_charged_not_what_the_line_says_now",
        ),
    ),
    # ---- the merchant's quote (Task 5, spec item 3b)
    Mutation(
        name="quote_not_recorded",
        breaks="a charge dispute has only our own number in it",
        edits=(
            (
                PLACEMENT,
                "        merchant_expected_price_usd=(body.expected_price,),",
                "        merchant_expected_price_usd=None,",
            ),
        ),
        tests=(PLACE,),
        expect=("test_the_merchants_own_quote_is_recorded_beside_the_price_we_charged",),
    ),
    Mutation(
        name="quote_never_stored",
        breaks="the column is threaded through and then dropped on the floor",
        edits=(
            (
                ORDERS,
                "                merchant_expected_price_usd=(\n"
                "                    None\n"
                "                    if merchant_expected_price_usd is None\n"
                "                    else merchant_expected_price_usd[index]\n"
                "                ),",
                "                merchant_expected_price_usd=None,",
            ),
        ),
        tests=(PLACE,),
        expect=("test_the_merchants_own_quote_is_recorded_beside_the_price_we_charged",),
    ),
    Mutation(
        name="quote_from_a_retail_actor",
        breaks="a retail line can carry a merchant's figure, so NULL stops meaning anything",
        edits=(
            (
                ORDERS,
                "        if actor.merchant_id is None:\n"
                '            raise ValidationError("a merchant quote is only accepted from a merchant actor")',
                "        if False:\n"
                '            raise ValidationError("a merchant quote is only accepted from a merchant actor")',
            ),
        ),
        tests=(ACTOR,),
        expect=("test_a_merchant_quote_from_a_retail_actor_is_refused",),
    ),
    Mutation(
        name="quote_length_unchecked",
        breaks="a short sequence is an IndexError on the money endpoint",
        edits=(
            (
                ORDERS,
                "        if len(merchant_expected_price_usd) != len(body.items):",
                "        if False:",
            ),
        ),
        tests=(ACTOR,),
        expect=("test_a_merchant_quote_must_line_up_with_the_lines",),
    ),
    # ---- the ledger key
    Mutation(
        name="colliding_refund_key",
        breaks="the refund replays the charge and the deposit never moves",
        edits=(
            (
                REFUND,
                'REFUND_KEY_PREFIX: Final = "merchant-order-refund:"',
                'REFUND_KEY_PREFIX: Final = "merchant-order:"',
            ),
        ),
        tests=(LIVE, KEYS),
        expect=(
            "test_a_force_complete_after_a_refund_is_refused_too",
            "test_a_frozen_merchant_is_still_refunded",
            "test_a_g2b_invalid_player_id_refunds_the_merchant_end_to_end",
            "test_a_hand_credit_cannot_take_an_order_past_what_it_charged",
            "test_a_partial_settlement_does_not_claim_the_order_was_refunded",
            "test_a_re_driven_fulfilment_refunds_once",
            "test_a_returned_failure_returns_the_charge_to_the_deposit",
            "test_an_admin_retry_after_a_refund_cannot_deliver_free_goods",
            "test_an_order_support_already_settled_is_not_refunded_again",
            "test_cancelling_an_already_refunded_order_says_nothing",
            "test_neither_key_family_can_contain_the_other",
            "test_the_refund_announces_the_money_by_push",
            "test_the_refund_is_visible_on_the_order_and_on_the_statement",
            "test_the_refund_is_what_we_charged_not_what_the_line_says_now",
            "test_the_two_keys_for_one_order_are_different_strings",
            "test_two_drainers_on_two_connections_refund_once",
        ),
    ),
    Mutation(
        name="refund_key_nested_in_the_charge_namespace",
        breaks="a key family that CAN collide, for an order id that happens to start with the tail",
        edits=(
            (
                REFUND,
                'REFUND_KEY_PREFIX: Final = "merchant-order-refund:"',
                'REFUND_KEY_PREFIX: Final = "merchant-order:refund-"',
            ),
        ),
        tests=(KEYS,),
        expect=("test_neither_key_family_can_contain_the_other",),
    ),
    # ---- idempotency and the two settlement paths
    Mutation(
        name="no_replay_before_the_guard",
        breaks="a re-driven fulfilment refuses itself over the money it already returned",
        edits=((REFUND, "    if existing is not None:\n        return existing\n\n", ""),),
        tests=(LIVE,),
        expect=(
            "test_a_re_driven_fulfilment_refunds_once",
            "test_the_refund_announces_the_money_by_push",
        ),
    ),
    Mutation(
        name="no_already_settled_check",
        breaks="a hand settlement and the automatic refund both pay one order",
        edits=(
            (
                REFUND,
                "    if already > 0:\n"
                "        raise AlreadySettledError(\n"
                '            f"order {order_id} already had {already} returned by another route"\n'
                "        )\n",
                "",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_partial_settlement_does_not_claim_the_order_was_refunded",
            "test_an_order_support_already_settled_is_not_refunded_again",
        ),
    ),
    Mutation(
        name="no_over_settlement_cap",
        breaks="a hand credit takes refunded_usd past the order's own price",
        edits=(
            (
                DEPOSIT,
                "        if not replayed:",
                "        if False:",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_hand_credit_cannot_take_an_order_past_what_it_charged",),
    ),
    Mutation(
        name="cap_runs_on_replays",
        breaks="an operator's own timeout retry answers 409 instead of replaying",
        edits=(
            (
                DEPOSIT,
                "        if not replayed:",
                "        if True:",
            ),
        ),
        tests=(LIVE, ATTRIB),
        expect=("test_the_cap_does_not_break_the_operators_own_retry",),
    ),
    # ---- the free-goods loophole, both doors
    Mutation(
        name="no_retry_guard",
        breaks="Retry after a refund delivers goods nobody paid for",
        edits=(
            (
                SAGA,
                '    await _refuse_a_settled_merchant_order(db, task=task)\n    task.status = "pending"',
                '    task.status = "pending"',
            ),
        ),
        tests=(LIVE,),
        expect=("test_an_admin_retry_after_a_refund_cannot_deliver_free_goods",),
    ),
    Mutation(
        name="no_force_complete_guard",
        breaks="the other admin button hands the artifact over after a refund",
        edits=(
            (
                SAGA,
                "    await _refuse_a_settled_merchant_order(db, task=task)\n"
                "    if artifact_kind not in _VALID_ARTIFACT_KINDS:",
                "    if artifact_kind not in _VALID_ARTIFACT_KINDS:",
            ),
        ),
        tests=(LIVE,),
        expect=("test_a_force_complete_after_a_refund_is_refused_too",),
    ),
    # ---- what the reseller and the operator are told
    Mutation(
        name="failure_reason_never_says_refunded",
        breaks="a reseller cannot tell a refund from a case a human is still deciding",
        edits=(
            (
                STATUS,
                "        return REASON_FULFILLMENT_REFUNDED if whole else REASON_FULFILLMENT_FAILED",
                "        return REASON_FULFILLMENT_FAILED",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_g2b_invalid_player_id_refunds_the_merchant_end_to_end",
            "test_the_refund_is_visible_on_the_order_and_on_the_statement",
        ),
    ),
    Mutation(
        name="failure_reason_claims_a_refund_that_did_not_post",
        breaks="the field announces money that never moved",
        edits=(
            (
                STATUS,
                "        return REASON_FULFILLMENT_REFUNDED if whole else REASON_FULFILLMENT_FAILED",
                "        return REASON_FULFILLMENT_REFUNDED",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_failed_refund_leaves_the_order_saying_a_human_is_deciding",
            "test_a_failure_that_did_not_return_our_money_refunds_nothing[spent]",
            "test_a_failure_that_did_not_return_our_money_refunds_nothing[unknown]",
            "test_a_g2b_rejection_we_do_not_recognise_still_parks_the_merchant_order",
            "test_a_manually_failed_merchant_order_reaches_the_seam",
            "test_a_partial_settlement_does_not_claim_the_order_was_refunded",
        ),
    ),
    Mutation(
        name="no_alert_when_a_human_is_needed",
        breaks="a spent/unknown merchant failure parks silently",
        edits=(
            (
                SAGA,
                "        _dispatch_alert(\n"
                "            _alert_merchant_needs_a_human(\n"
                "                task_id=task_id, order_id=order_id, supplier=supplier, outcome=outcome\n"
                "            )\n"
                "        )\n",
                "",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_failure_that_did_not_return_our_money_refunds_nothing[spent]",
            "test_a_failure_that_did_not_return_our_money_refunds_nothing[unknown]",
            "test_a_g2b_rejection_we_do_not_recognise_still_parks_the_merchant_order",
            "test_a_manually_failed_merchant_order_reaches_the_seam",
        ),
    ),
    Mutation(
        name="no_alert_when_the_refund_fails",
        breaks="a refund that could not post is a log line nobody reads",
        edits=(
            (
                SAGA,
                "            _dispatch_alert(\n"
                "                _alert_merchant_refund_failed(\n"
                '                    task_id=task_id, order_id=seen.get("order_id"), error=detail\n'
                "                )\n"
                "            )\n",
                "",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_fault_in_the_merchant_gate_is_reported_not_fatal",
            "test_a_fault_in_the_seams_own_reads_is_reported_not_fatal",
            "test_a_partial_settlement_does_not_claim_the_order_was_refunded",
            "test_a_refund_failure_leaves_the_task_refundable",
            "test_an_order_support_already_settled_is_not_refunded_again",
            "test_an_order_with_no_charge_refunds_nothing_and_calls_a_human",
            "test_an_unexpected_refund_crash_never_reaches_the_unknown_crash_arm",
            "test_an_unimportable_refund_module_is_reported_not_fatal",
        ),
    ),
    # ---- the one supplier rejection we grade as free (M3c Task 1)
    #
    # These sit here rather than in a g2b harness of their own because what
    # they break is a *money* property: the predicate below is the only thing
    # standing between "G2B refused" and a posted refund, and its false
    # positive spends our money on a merchant who is not owed it.
    #
    # The last six break **one way of being wrong each**, counted by hand off
    # ``_is_an_unbilled_player_rejection`` — the cheap manual version of a
    # generated dropper, and the same method that turned up two missing rows
    # in the webhook harness. The predicate has six decisions (status, "is it
    # JSON", "is it an object", ``success is False``, "is the message text",
    # and whether the **whole** normalised message equals the observed one);
    # the last of those has three rows, because the three ways to loosen an
    # equality — prefix, substring, and not checking at all — admit different
    # families of message and one of them is how 77a2efe0 shipped.
    #
    # **Every row runs both unit files.** Two of them declared only
    # ``G2B_UNIT`` in the first round while the report claimed they graded
    # cases living in ``OUTCOME``; the runner opens a row's declared files and
    # nothing else, so those cases were graded by nothing at all.
    Mutation(
        name="invalid_player_not_graded",
        breaks="the one rejection we know is free goes back to parking for a human",
        edits=(
            (
                G2B,
                "                money_outcome=(\n"
                "                    _REJECTED_UNBILLED if _is_an_unbilled_player_rejection(exc) else _MAY_HAVE_SPENT\n"
                "                ),\n",
                "                money_outcome=_MAY_HAVE_SPENT,\n",
            ),
        ),
        tests=(OUTCOME, LIVE),
        expect=(
            "test_a_g2b_invalid_player_id_refunds_the_merchant_end_to_end",
            "test_g2b_an_invalid_player_id_is_money_we_never_spent",
            "test_the_same_g2b_rejection_moves_no_money_for_a_retail_order",
            "test_the_unbilled_player_rejection_is_consulted_at_exactly_one_site",
        ),
    ),
    Mutation(
        name="unbilled_beats_low_balance",
        breaks="a body claiming both refunds a reseller instead of stalling for a top-up",
        edits=(
            (
                G2B,
                "            if _looks_like_low_balance(exc):\n"
                "                return _low_balance_result(\n"
                "                    mapping=mapping,\n"
                '                    kind="game",\n',
                "            if _looks_like_low_balance(exc) and not _is_an_unbilled_player_rejection(\n"
                "                exc\n"
                "            ):\n"
                "                return _low_balance_result(\n"
                "                    mapping=mapping,\n"
                '                    kind="game",\n',
            ),
        ),
        tests=(OUTCOME,),
        expect=(
            "test_g2b_the_low_balance_branch_still_wins_a_body_that_matches_both",
            "test_the_unbilled_player_rejection_is_consulted_at_exactly_one_site",
        ),
    ),
    Mutation(
        name="predicate_copied_onto_the_voucher_raise",
        breaks="the ruling for a game create is applied to a voucher purchase",
        # The concrete way the single-call-site rule dies: a two-line copy
        # onto the sibling raise. The voucher branch never sends a player id,
        # so a voucher body carrying that message is evidence of nothing.
        edits=(
            (
                G2B,
                '                f"g2b purchase failed: HTTP {exc.status}: {_err_body(exc)}",\n'
                "                money_outcome=_MAY_HAVE_SPENT,\n",
                '                f"g2b purchase failed: HTTP {exc.status}: {_err_body(exc)}",\n'
                "                money_outcome=(\n"
                "                    _REJECTED_UNBILLED\n"
                "                    if _is_an_unbilled_player_rejection(exc)\n"
                "                    else _MAY_HAVE_SPENT\n"
                "                ),\n",
            ),
        ),
        tests=(OUTCOME,),
        expect=("test_the_unbilled_player_rejection_is_consulted_at_exactly_one_site",),
    ),
    Mutation(
        name="matcher_ignores_the_status",
        breaks="a 5xx carrying their words is read as a free refusal",
        edits=(
            (
                G2B,
                "    if exc.status != _INVALID_PLAYER_STATUS:\n        return False\n",
                "",
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=(
            "test_g2b_a_rejection_we_do_not_recognise_is_still_unknown[a-500]",
            "test_the_right_words_at_the_wrong_status_are_not_recognised",
        ),
    ),
    Mutation(
        name="matcher_reads_a_non_json_body",
        breaks="an HTML page or a proxy carrying their words is read as G2B",
        edits=(
            (
                G2B,
                "    except (json.JSONDecodeError, TypeError):\n"
                "        # Not their JSON at all — an HTML error page, a proxy, a truncated\n"
                "        # body. Whatever rejected us, it was not G2B saying this.\n"
                "        return False\n",
                "    except (json.JSONDecodeError, TypeError):\n"
                '        body = {"success": False, "message": exc.body}\n',
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=("test_only_g2bs_own_invalid_player_shape_is_recognised[not-their-envelope]",),
    ),
    Mutation(
        name="matcher_ignores_the_body_shape",
        breaks="a bare JSON string is asked for a success flag it cannot have",
        edits=(
            (
                G2B,
                '    if not isinstance(body, dict) or body.get("success") is not False:\n',
                '    if body.get("success") is not False:\n',
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=("test_only_g2bs_own_invalid_player_shape_is_recognised[json-not-an-object]",),
    ),
    Mutation(
        name="matcher_ignores_the_success_flag",
        breaks="their envelope saying success is read as their refusal",
        edits=(
            (
                G2B,
                '    if not isinstance(body, dict) or body.get("success") is not False:\n',
                "    if not isinstance(body, dict):\n",
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=("test_only_g2bs_own_invalid_player_shape_is_recognised[not-a-refusal]",),
    ),
    Mutation(
        name="matcher_trusts_a_non_string_message",
        breaks="a message that is not text reaches the pattern and raises",
        edits=(
            (
                G2B,
                "    if not isinstance(message, str):\n        return False\n",
                "",
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=("test_only_g2bs_own_invalid_player_shape_is_recognised[message-not-a-string]",),
    ),
    Mutation(
        name="matcher_matches_a_prefix",
        breaks="a rejection that only *opens* with their words is read as this one",
        # This restores exactly what 77a2efe0 shipped (an anchored pattern
        # consumed by ``re.match``), and the review found it by probing
        # ``"Invalid player ID; the order was created and charged"`` — a
        # refusal we were **billed** for, wearing the words of one we were
        # not. The row exists so the regression cannot come back quietly.
        edits=(
            (
                G2B,
                '    return " ".join(message.split()).lower() == _INVALID_PLAYER_MESSAGE\n',
                '    return " ".join(message.split()).lower().startswith("invalid player id")\n',
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=(
            "test_only_g2bs_own_invalid_player_shape_is_recognised[longer-word-at-the-anchor]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[reworded-suffix]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[shortened-variant]",
        ),
    ),
    Mutation(
        name="matcher_matches_a_substring",
        breaks="their words buried inside a longer rejection are read as this one",
        edits=(
            (
                G2B,
                '    return " ".join(message.split()).lower() == _INVALID_PLAYER_MESSAGE\n',
                '    return _INVALID_PLAYER_MESSAGE in " ".join(message.split()).lower()\n',
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=("test_only_g2bs_own_invalid_player_shape_is_recognised[prefix-before-the-phrase]",),
    ),
    Mutation(
        name="matcher_ignores_the_message",
        breaks="every rejection under their envelope becomes a free one",
        edits=(
            (
                G2B,
                '    return " ".join(message.split()).lower() == _INVALID_PLAYER_MESSAGE\n',
                "    return True\n",
            ),
        ),
        tests=(G2B_UNIT, OUTCOME),
        expect=(
            "test_g2b_a_rejection_we_do_not_recognise_is_still_unknown[another-400]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[another-message]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[longer-word-at-the-anchor]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[phrase-buried-mid-message]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[prefix-before-the-phrase]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[reworded-suffix]",
            "test_only_g2bs_own_invalid_player_shape_is_recognised[shortened-variant]",
        ),
    ),
    Mutation(
        name="no_balance_credited_event",
        breaks="the automatic path stops announcing money the hand path announces",
        edits=(
            (
                REFUND,
                "    await webhooks.enqueue_balance_credited(\n"
                "        db,\n"
                "        merchant_id=merchant_id,\n"
                "        amount=charged,\n"
                "        balance=await deposit_balance(db, merchant_id=merchant_id),\n"
                "    )\n",
                "",
            ),
        ),
        tests=(LIVE,),
        expect=("test_the_refund_announces_the_money_by_push",),
    ),
)


if __name__ == "__main__":
    sys.exit(main(MUTATIONS, description=__doc__))
