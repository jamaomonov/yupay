#!/usr/bin/env python
"""Mutation harness for the merchant webhook **producer** (M3a, Task 3).

Every property in ``merchants/webhooks.py`` and in the status-change seam is
only as good as the test that goes red when it is removed. This script breaks
each one in turn and checks that the named tests actually fail — the
difference between "the suite passes" and "the suite would notice".

The runner, the guarantees it enforces and the rules for running one live in
:mod:`_falsify`; read that first. Run it::

    uv run python apps/api/tests/tools/falsify_merchant_webhook_events.py
    uv run python apps/api/tests/tools/falsify_merchant_webhook_events.py -k notify
    uv run python apps/api/tests/tools/falsify_merchant_webhook_events.py --check-anchors

Committed for the reason ``falsify_outbound.py`` is: a falsification result
nobody can re-run is a claim, not evidence. It found the same class of problem
once during Task 3: the first attempt at the ``url``-snapshot mutation was
*equivalent to the original code* (re-reading the hook's URL at enqueue time
yields the same value it already had), so it could not have failed. The
mutation that does bite is the plausible regression on the **config** path — a
well-meaning "keep the log tidy" UPDATE, which is exactly what joining the log
onto ``merchant_webhooks`` would amount to.

It also carried the ambiguous anchor that :mod:`_falsify` now refuses. See
``replay_announced`` below for what that cost.

**Every row runs the whole integration file**, not the one test it names, so
the exact ``expect=`` set can see collateral damage. Fourteen tests in about
fifteen seconds; a narrower ``tests=`` would make the exactness vacuous.
"""

from __future__ import annotations

import sys

from _falsify import SRC, Mutation, main

EVENTS = "apps/api/tests/integration/test_merchant_webhook_events.py"

HOOKS = SRC / "modules/merchants/webhooks.py"
DEPOSIT = SRC / "modules/merchants/deposit.py"
ADMIN = SRC / "modules/merchants/admin.py"
ORDERS = SRC / "modules/orders/service.py"
FULFILMENT = SRC / "modules/fulfillment/service.py"


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="disabled_ignored",
        breaks="a disabled hook still collects rows nobody will deliver",
        edits=((HOOKS, "                MerchantWebhook.disabled_at.is_(None),\n", ""),),
        tests=(EVENTS,),
        expect=("test_a_disabled_webhook_enqueues_nothing",),
    ),
    Mutation(
        name="no_savepoint",
        breaks="a failed insert poisons the session instead of rolling back alone",
        edits=((HOOKS, "        async with db.begin_nested():\n", "        if True:\n"),),
        tests=(EVENTS,),
        expect=("test_an_enqueue_that_raises_does_not_roll_back_the_order",),
    ),
    Mutation(
        name="no_notify",
        breaks="the row lands but the worker is never woken",
        edits=(
            (
                HOOKS,
                "            await db.execute(\n"
                '                text("SELECT pg_notify(:channel, :id)"),\n'
                '                {"channel": WEBHOOK_QUEUE_CHANNEL, "id": delivery_id},\n'
                "            )\n",
                "",
            ),
        ),
        tests=(EVENTS,),
        expect=("test_a_rolled_back_transaction_leaves_no_row_and_fires_no_notify",),
    ),
    Mutation(
        name="channel_typo",
        breaks="the producer and Task 4's listener stop agreeing on the channel",
        edits=(
            (
                HOOKS,
                'WEBHOOK_QUEUE_CHANNEL: Final = "merchant_webhook_queue"',
                'WEBHOOK_QUEUE_CHANNEL: Final = "merchant_webhooks_queue"',
            ),
        ),
        tests=(EVENTS,),
        expect=("test_the_channel_name_is_the_one_task_four_listens_on",),
    ),
    Mutation(
        name="code_in_payload",
        breaks="a bearer instrument is smuggled into a body the receiver logs",
        edits=(
            (
                HOOKS,
                '            "status": order.status,\n',
                '            "status": order.status,\n            "code": "GIFT-CODE-1234",\n',
            ),
        ),
        tests=(EVENTS,),
        expect=(
            "test_a_merchant_order_enqueues_paid_and_fulfilling_with_an_exact_payload",
            "test_delivering_the_order_enqueues_delivered_and_never_the_code",
        ),
    ),
    Mutation(
        # The anchor carries the comment line below it, and must. The bare
        # ``"    if not replayed:"`` this row used to use is a **substring** of
        # the eight-space ``if not replayed:`` that M3b's over-settlement guard
        # added earlier in the same file, so ``str.replace`` landed the mutation
        # on that branch instead — a branch this test never enters, because it
        # credits with no ``order_id``. The row then reported a surviving
        # mutation: a false alarm rather than a quiet pass, which is the only
        # reason it was not believed. ``--check-anchors`` reports it now.
        name="replay_announced",
        breaks="a replayed credit announces money that did not move",
        edits=(
            (
                DEPOSIT,
                "    if not replayed:\n"
                "        # In this transaction, with the credit, so a merchant is told about\n",
                "    if True:\n"
                "        # In this transaction, with the credit, so a merchant is told about\n",
            ),
        ),
        tests=(EVENTS,),
        expect=("test_a_replayed_credit_enqueues_nothing_the_second_time",),
    ),
    Mutation(
        name="settle_publishes_realtime",
        breaks="every retail delivery gains a realtime event it never had",
        edits=(
            (
                FULFILMENT,
                "    await _publish_status_changed(db, order, publish_realtime=False)\n",
                "    await _publish_status_changed(db, order)\n",
            ),
        ),
        tests=(EVENTS,),
        expect=("test_a_retail_delivery_still_publishes_only_order_delivered",),
    ),
    Mutation(
        name="settle_not_hooked",
        breaks="`delivered` -- the event a reseller waits for -- is never emitted",
        edits=(
            (
                FULFILMENT,
                "    await _publish_status_changed(db, order, publish_realtime=False)\n",
                "",
            ),
        ),
        tests=(EVENTS,),
        expect=("test_delivering_the_order_enqueues_delivered_and_never_the_code",),
    ),
    Mutation(
        name="paid_not_hooked",
        breaks="the status a merchant order is born in is never announced",
        edits=(
            (ORDERS, "    await on_order_status_changed(db, order, publish_realtime=False)\n", ""),
        ),
        tests=(EVENTS,),
        expect=(
            "test_a_merchant_order_enqueues_paid_and_fulfilling_with_an_exact_payload",
            "test_an_enqueue_that_raises_does_not_roll_back_the_order",
            "test_delivering_the_order_enqueues_delivered_and_never_the_code",
        ),
    ),
    # NOT a mutation of ``url=hook.url``: the column is NOT NULL, so an enqueue
    # must write *some* URL, and re-reading the same row at enqueue time yields
    # the same value. The regression the snapshot exists to prevent lives on the
    # config path -- an UPDATE that "tidies" the log, which is what a join onto
    # ``merchant_webhooks`` would amount to.
    Mutation(
        name="set_webhook_rewrites_history",
        breaks="moving an endpoint re-attributes every historical delivery to it",
        edits=(
            (
                ADMIN,
                "        hook.url = clean\n",
                "        hook.url = clean\n"
                "        from yupay.modules.merchants.models import MerchantWebhookDelivery\n"
                "        await db.execute(update(MerchantWebhookDelivery)"
                ".where(MerchantWebhookDelivery.merchant_id == merchant_id).values(url=clean))\n",
            ),
        ),
        tests=(EVENTS,),
        expect=("test_the_url_is_snapshotted_at_enqueue_and_a_later_move_does_not_rewrite_it",),
    ),
)


if __name__ == "__main__":
    sys.exit(main(MUTATIONS, description=__doc__))
