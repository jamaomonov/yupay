#!/usr/bin/env python
"""Mutation harness for the stall value (M3b, Task 4).

Same contract as its four siblings: break one property at a time and check
that the named tests actually go red. Copied from ``falsify_merchant_refund``
rather than from the older three, because that one carries the two mechanisms
three review rounds produced — an **exact** expected red set per row, and
``--check-anchors`` — and both exist because their absence hid a defect here
before.

**Why this task needs a harness at all**, when its own tests were observed red
before the implementation: two of its properties are guaranteed by code this
task did not write and cannot exercise by adding a test.

* **Retail must not change** — and the guarantee is ``_apply_failure``'s
  low-balance early return, which predates this task. A retail test that
  merely passes proves nothing, because it passed before the change too. Row
  ``no_low_balance_early_return`` is the proof: delete the guarantee and the
  storefront comparison fails.
* **The precedence** — ``order_failed`` and a terminal delivery failure
  outrank the stall. Every ingredient is individually right, so the ordering
  is what a test has to pin, and the only way to falsify an ordering is to
  reorder it.
* **The scoping** — every test here builds its orders in a TRUNCATE-isolated
  database, so the clause that scopes the read to *this* order could be
  deleted with the whole integration selection still green (measured: 679
  passed, 0 failed). ``stall_ignores_the_order`` plus the two-merchant test it
  reddens are what stopped one reseller's stall from publishing
  ``fulfillment_delayed`` on everybody else's healthy orders — this task's own
  harm, inverted.

  **M3c Task 3 moved that property, and the row had to move with it.** The
  predicate became a batch (``stalled_order_ids``) so the admin order list
  could ask it once per page; it now returns a *set of ids* that both callers
  intersect with the order in hand, so deleting the scoping clause can no
  longer make anyone answer "delayed" about a healthy order — the harm is
  structural now, and the two-merchant test went **green** under the mutation.
  Rather than delete a row that had stopped grading anything, it is re-pointed
  at ``test_the_batched_predicate_answers_only_about_the_orders_it_was_asked``,
  which asserts what the clause still guarantees: the function never returns an
  id nobody asked about. That is what the next caller — "which of this page is
  stuck?" — would iterate.

**Two rows here exist because they were found vacuous first.**
``stall_ignores_the_item_state`` reported ``UNFALSIFIED`` until a two-**line**
order gave the item half something to be wrong about, and
``stall_ignores_the_order`` was added after a review deleted that one line and
watched nothing fail. Both are the same lesson: a mutation that grades nothing
is worse than no row, and the only fix is the test shape that reaches the half.

The runner, the guarantees it enforces and the rules for running one live in
:mod:`_falsify`; read that first. Run it::

    uv run python apps/api/tests/tools/falsify_merchant_stall.py
    uv run python apps/api/tests/tools/falsify_merchant_stall.py -k retail
    uv run python apps/api/tests/tools/falsify_merchant_stall.py --check-anchors

## One property is deliberately not falsifiable here

**"The value never names its cause"** is an *absence*: ``_failure_reason``
takes a ``bool`` and has no access to the supplier, the balance or the error
string, so there is no line to delete. ``stall_names_its_cause`` falsifies the
nearest reachable thing instead — the published word itself made into the
sentinel — which is a real leak and is what the body assertion in
``test_the_stall_never_says_why_it_stalled`` exists to catch. What it does not
cover is somebody widening the signature to pass the task in; that would be a
design change, not a regression, and it would arrive with its own review.
Stated rather than left implicit, because on this branch a declared absence has
twice turned out to be falsifiable after all: re-derive this one if the
signature ever moves.
"""

from __future__ import annotations

import sys

from _falsify import SRC, Mutation, main

STALL_TESTS = "apps/api/tests/integration/test_merchant_order_stall.py"
TABLE_TESTS = "apps/api/tests/unit/test_merchant_failure_reason.py"

SAGA = SRC / "modules/fulfillment/service.py"
STALL = SRC / "modules/fulfillment/stall.py"
STATUS = SRC / "modules/merchants/order_status.py"

#: Every row runs the same two files, so the blast radii below are comparable
#: with each other. Broader suites are the commit's gate, not this file's job.
TESTS = (STALL_TESTS, TABLE_TESTS)


MUTATIONS: tuple[Mutation, ...] = (
    # ---- the guarantee this task rests on and did not write
    Mutation(
        name="no_low_balance_early_return",
        breaks="a stall becomes an ordinary failure, and the storefront shows an error",
        edits=((SAGA, "    if result.error == _LOW_BALANCE_ERROR:", "    if False:"),),
        tests=TESTS,
        expect=(
            "test_a_line_that_terminally_failed_does_not_stall_the_line_beside_it",
            "test_a_second_stall_still_reads_as_delayed",
            "test_a_supplier_low_balance_stall_says_the_order_is_delayed",
            "test_a_terminal_failure_can_become_a_delay_again",
            "test_a_top_up_and_a_successful_retry_clear_the_stall",
            "test_one_merchants_stall_does_not_delay_another_merchants_order",
            "test_the_batched_predicate_answers_only_about_the_orders_it_was_asked",
            "test_the_stall_never_says_why_it_stalled",
            "test_the_storefront_cannot_tell_a_stalled_order_from_a_busy_one",
        ),
    ),
    # ---- the value itself
    Mutation(
        name="the_stall_is_never_reported",
        breaks="the whole feature: a stalled order goes back to saying nothing",
        edits=(
            (
                STATUS,
                "    return REASON_FULFILLMENT_DELAYED if stalled else None",
                "    return None",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_second_stall_still_reads_as_delayed",
            "test_a_stall_is_never_reported_for_an_order_with_no_charge_on_file",
            "test_a_supplier_low_balance_stall_says_the_order_is_delayed",
            "test_a_terminal_failure_can_become_a_delay_again",
            "test_a_top_up_and_a_successful_retry_clear_the_stall",
            "test_one_merchants_stall_does_not_delay_another_merchants_order",
            "test_the_failure_reason_table[stalled-fulfilling-in_progress-True-refunded3-fulfillment_delayed]",
            "test_the_stall_never_says_why_it_stalled",
        ),
    ),
    Mutation(
        name="stall_names_its_cause",
        breaks="the published word tells a reseller which supplier we are short at",
        edits=(
            (
                STATUS,
                'REASON_FULFILLMENT_DELAYED: Final = "fulfillment_delayed"',
                'REASON_FULFILLMENT_DELAYED: Final = "supplier_low_balance"',
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_second_stall_still_reads_as_delayed",
            "test_a_supplier_low_balance_stall_says_the_order_is_delayed",
            "test_a_terminal_failure_can_become_a_delay_again",
            "test_a_top_up_and_a_successful_retry_clear_the_stall",
            "test_one_merchants_stall_does_not_delay_another_merchants_order",
            "test_the_delayed_value_never_names_its_cause",
            "test_the_stall_never_says_why_it_stalled",
        ),
    ),
    # ---- the precedence, which is the contract and not an implementation detail
    Mutation(
        name="stall_outranks_a_hand_closure",
        breaks="an order support closed by hand tells the reseller to keep waiting",
        edits=(
            (
                STATUS,
                '    if order.status == "failed":\n        return REASON_ORDER_FAILED\n',
                "    if stalled:\n"
                "        return REASON_FULFILLMENT_DELAYED\n"
                '    if order.status == "failed":\n'
                "        return REASON_ORDER_FAILED\n",
            ),
        ),
        tests=TESTS,
        # Two rows, not three, and the id suffixes moved: M3c Task 6 added rows
        # to the table (renumbering the parametrize ids) **and** put the
        # refunded branch ahead of the status one, so ``stalled and refunded``
        # is now decided before either injected stall check can see it. That
        # row is graded by ``falsify_merchant_refund``'s three
        # ``order_status`` rows instead, which now open this file for exactly
        # that reason.
        expect=(
            "test_the_failure_reason_table[stalled and closed-failed-in_progress-True-refunded11-order_failed]",
            "test_the_failure_reason_table[stalled and failed-fulfilling-failed-True-refunded12-fulfillment_failed]",
        ),
    ),
    Mutation(
        name="stall_outranks_a_terminal_failure",
        breaks="a delivery that terminally failed tells the reseller to keep waiting",
        edits=(
            (
                STATUS,
                '    if order.status == "failed":\n        return REASON_ORDER_FAILED\n',
                '    if order.status == "failed":\n'
                "        return REASON_ORDER_FAILED\n"
                "    if stalled:\n"
                "        return REASON_FULFILLMENT_DELAYED\n",
            ),
        ),
        tests=TESTS,
        # One row, not two — same reason as the sibling above.
        expect=(
            "test_the_failure_reason_table[stalled and failed-fulfilling-failed-True-refunded12-fulfillment_failed]",
        ),
    ),
    # ---- the predicate's two halves
    Mutation(
        name="stall_ignores_the_order",
        breaks="the batch answers about orders nobody asked about",
        # **What this row grades moved with M3c Task 3, and pretending it did
        # not would have left it vacuous.** The predicate became a batch
        # (``stalled_order_ids``, with ``order_is_stalled`` as its one-element
        # case) so the admin order list could ask it once per page. The batch
        # returns a *set of ids* and both callers intersect it with the order in
        # hand — so deleting the scoping clause no longer makes anyone answer
        # "delayed" about a healthy order, and
        # ``test_one_merchants_stall_does_not_delay_another_merchants_order``
        # went green under this mutation. The cross-order harm is now
        # structural, which is a stronger place for it to live than a WHERE
        # clause.
        #
        # What the clause still guarantees is the function's published promise —
        # *never contains an id that was not asked for* — which the next caller
        # (an admin "which of this page is stuck?" view is the obvious one)
        # would iterate. So the row is re-pointed at the test that asserts that
        # promise directly, rather than deleted or left reporting UNFALSIFIED.
        edits=((STALL, "                FulfillmentTask.order_id.in_(candidates),\n", ""),),
        tests=TESTS,
        expect=("test_the_batched_predicate_answers_only_about_the_orders_it_was_asked",),
    ),
    Mutation(
        name="stall_ignores_the_task_status",
        breaks="every order with an open item reads as delayed, including a busy one",
        edits=((STALL, '                FulfillmentTask.status == "failed",\n', ""),),
        tests=TESTS,
        expect=(
            "test_a_line_that_terminally_failed_does_not_stall_the_line_beside_it",
            "test_a_terminally_failed_order_is_not_stalled",
            "test_an_order_still_in_flight_is_not_delayed",
            "test_one_merchants_stall_does_not_delay_another_merchants_order",
            "test_the_batched_predicate_answers_only_about_the_orders_it_was_asked",
        ),
    ),
    Mutation(
        name="stall_ignores_the_item_state",
        breaks="a terminally failed order answers the predicate yes",
        edits=(
            (
                STALL,
                "                OrderItem.fulfillment_state.in_(UNSETTLED_ITEM_STATES),\n",
                "",
            ),
        ),
        tests=TESTS,
        expect=("test_a_line_that_terminally_failed_does_not_stall_the_line_beside_it",),
    ),
    Mutation(
        name="no_short_circuit",
        breaks="a settled order pays a database round trip on every poll",
        # Deleting the filter is not an option post-batch — the comprehension
        # *is* the list the query reads — so the mutation keeps every order as
        # a candidate instead. Same effect: a page (or a poll) with nothing
        # open on it now pays for a round trip.
        edits=(
            (
                STALL,
                "        if any(item.fulfillment_state in UNSETTLED_ITEM_STATES "
                "for item in order.items)\n",
                "",
            ),
        ),
        tests=TESTS,
        expect=("test_a_settled_order_costs_no_stall_query",),
    ),
)


if __name__ == "__main__":
    sys.exit(main(MUTATIONS, description=__doc__))
