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

Run it::

    uv run python apps/api/tests/tools/falsify_merchant_refund.py
    uv run python apps/api/tests/tools/falsify_merchant_refund.py -k gate

**Run nothing else against this worktree while this is running.** It edits
source files in place, so any concurrently running suite imports whatever
mutation happens to be applied at that moment and fails for reasons that have
nothing to do with it.

``--check-anchors`` applies every edit **in memory** and reports all the stale
ones at once, in about a second. Run it after any refactor near the seam: the
real run aborts on the first stale anchor, which is correct and costs a pytest
round trip per discovery, and five of them accumulated in a single round here.

Sources are restored from a copy taken before the edit, in a ``finally``.
Never ``git checkout`` — several agents share this worktree. pytest runs in
its own process group, killed as a group in a ``finally``: on SIGINT the group
dies and the tree comes back byte-identical; on SIGKILL neither runs and the
tree is left mutated, which is the reason not to ``kill -9`` this script.

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

import argparse
import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SRC = REPO / "apps/api/src/yupay"
LIVE = "apps/api/tests/integration/test_merchant_auto_refund.py"
KEYS = "apps/api/tests/unit/test_merchant_refund_keys.py"
ATTRIB = "apps/api/tests/integration/test_merchant_deposit_attribution.py"
#: Task 5's quote record. Not a refund, but the same money record: what a
#: reseller quoted is what a charge dispute is settled from, and it is written
#: on the order line the refund's amount is deliberately *not* read from.
PLACE = "apps/api/tests/integration/test_merchant_api_orders.py"
ACTOR = "apps/api/tests/integration/test_orders_merchant_actor.py"

REFUND = SRC / "modules/merchants/refund.py"
DEPOSIT = SRC / "modules/merchants/deposit.py"
STATUS = SRC / "modules/merchants/order_status.py"
SAGA = SRC / "modules/fulfillment/service.py"
PLACEMENT = SRC / "modules/merchants/orders.py"
ORDERS = SRC / "modules/orders/service.py"

#: ``FAILED apps/.../test_x.py::test_name[param] - AssertionError: …``.
_FAILED_LINE = re.compile(r"^FAILED\s+\S+?\.py::(?P<name>.+?)(?:\s+-\s.*)?$")


@dataclass(frozen=True)
class Mutation:
    """One way to break the refund, and the tests that must notice.

    Attributes:
        name: How the row is reported.
        breaks: What property this removes, for the report.
        edits: ``(path, old, new)`` triples. Each must change its file.
        tests: Test ids or files to run.
        expect: The **exact** set of tests this mutation must redden — not a
            subset. Equality is the point: the first version of this harness
            asserted only that the named tests were *among* the failures, and
            a row that reddened nine tests where three were expected passed
            silently for two review rounds. A blast radius that changes is a
            row grading something other than what it says, which is the same
            failure the ``SystemExit`` guard catches for anchors. Fill it in
            with ``--record``.
    """

    name: str
    breaks: str
    edits: tuple[tuple[Path, str, str], ...]
    tests: tuple[str, ...]
    expect: tuple[str, ...] = ()


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
        expect=("test_a_retail_failure_never_reaches_the_refund_at_all",),
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
        expect=("test_the_refund_is_visible_on_the_order_and_on_the_statement",),
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


def _check_anchors(chosen: list[Mutation]) -> int:
    """Report every stale anchor at once, in seconds, without touching the tree.

    The whole run aborts on the **first** stale anchor — deliberately, because
    a harness that carries on after one is a harness reporting on a tree it did
    not mutate. That is right and it is also slow: each discovery costs a
    pytest run, and five accumulated in one round here while the code moved
    under them. This finds all five in about a second, and it is the cheapest
    thing to run after any refactor near the seam.

    Args:
        chosen: The rows to check.

    Returns:
        A process exit code: non-zero if any anchor no longer matches.
    """
    cache: dict[Path, str] = {}
    stale: list[str] = []
    for mutation in chosen:
        edited: dict[Path, str] = {}
        for path, old, _new in mutation.edits:
            source = edited.get(path) or cache.setdefault(path, path.read_text())
            if old not in source:
                stale.append(f"{mutation.name:44} {path.name}  {old.splitlines()[0][:60]!r}")
                continue
            edited[path] = source.replace(old, _new, 1)
    for row in stale:
        print(f"STALE  {row}")
    print(f"\n{len(stale)} stale anchor(s) across {len(chosen)} rows")
    return 1 if stale else 0


def _apply(mutation: Mutation, backups: dict[Path, Path]) -> None:
    """Apply every edit, insisting each one actually changed its file."""
    for path, old, new in mutation.edits:
        if path not in backups:
            copy = Path(tempfile.mkdtemp(prefix="falsify-")) / path.name
            shutil.copy2(path, copy)
            backups[path] = copy
        source = path.read_text()
        mutated = source.replace(old, new, 1)
        if mutated == source:
            message = (
                f"{mutation.name}: the edit changed nothing in {path.name}. "
                "A str.replace that matches nothing is a silent no-op, and a "
                "harness that reports GREEN from one is worse than no harness."
            )
            raise SystemExit(message)
        path.write_text(mutated)


def _restore(backups: dict[Path, Path]) -> None:
    """Put every mutated file back from its pre-edit copy."""
    for path, copy in backups.items():
        shutil.copy2(copy, path)
        shutil.rmtree(copy.parent, ignore_errors=True)


def _run(mutation: Mutation) -> tuple[str, list[str]]:
    """Run the mutation's tests. Returns a verdict and the failing test names."""
    command = ["uv", "run", "pytest", *mutation.tests, "-q", "-p", "no:cacheprovider", "--no-cov"]
    process = subprocess.Popen(
        command,
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=900)
    except subprocess.TimeoutExpired:
        return "TIMED OUT", []
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    failures = sorted(
        {match.group("name") for line in stdout.splitlines() if (match := _FAILED_LINE.match(line))}
    )
    if process.returncode == 0:
        return "UNFALSIFIED — the suite stayed green", failures
    observed, expected = set(failures), set(mutation.expect)
    if observed == expected:
        return "failed as expected", failures
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    parts = []
    if missing:
        parts.append(f"did not red {', '.join(missing)}")
    if extra:
        parts.append(f"also red {', '.join(extra)}")
    return f"WRONG BLAST RADIUS — {'; '.join(parts)}", failures


def main() -> int:
    """Run every mutation (or those matching ``-k``) and print a table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-k", dest="pattern", default="", help="substring of the mutation name")
    parser.add_argument("--list", action="store_true", help="print the mutations and exit")
    parser.add_argument(
        "--check-anchors",
        action="store_true",
        help="apply every edit in memory and report stale anchors, without running pytest",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="print each row's observed red set as an `expect=` tuple, for pasting back",
    )
    args = parser.parse_args()

    chosen = [m for m in MUTATIONS if args.pattern in m.name]
    if args.list:
        for mutation in chosen:
            print(f"{mutation.name:44} {mutation.breaks}")
        return 0
    if args.check_anchors:
        return _check_anchors(chosen)

    print(
        "falsify: editing source files in place — do not run any other suite "
        "against this worktree until it finishes.\n",
        flush=True,
    )
    rows: list[tuple[str, str]] = []
    for mutation in chosen:
        backups: dict[Path, Path] = {}
        try:
            _apply(mutation, backups)
            verdict, failures = _run(mutation)
        finally:
            _restore(backups)
        rows.append((mutation.name, verdict))
        print(f"{mutation.name:44} {verdict}", flush=True)
        if args.record:
            body = "".join(f'\n            "{name}",' for name in failures)
            print(f"        # {mutation.name}\n        expect=({body}\n        ),", flush=True)

    print("\n--- summary ---")
    unfalsified = [
        name
        for name, verdict in rows
        if verdict.startswith(("UNFALSIFIED", "WRONG BLAST RADIUS", "TIMED OUT"))
    ]
    for name, verdict in rows:
        print(f"{name:44} {verdict}")
    if unfalsified:
        print(f"\n{len(unfalsified)} mutation(s) not falsified: {', '.join(unfalsified)}")
        return 1
    print(f"\nall {len(rows)} mutations falsified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
