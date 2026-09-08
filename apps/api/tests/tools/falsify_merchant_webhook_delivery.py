#!/usr/bin/env python
"""Mutation harness for the merchant webhook **delivery drain** (M3a, Task 4).

Break one property at a time and check the named tests actually go red. It
covers ``apps/worker``'s consumer loop as well as the three ``merchants``
modules, because the webhook queue shares a process with every retail order's
fulfilment and three of its properties are about that sharing. A test that
stays green under a mutation is a test that would not have noticed the
regression, and this file exists because one of them already did that here —
the first version of the enqueue-order test inserted its two rows in id order,
so Postgres returned them in physical order and the test passed with the
``ORDER BY`` tie-break deleted. It now inserts them in the **opposite** order
to their ids, and the ``no_id_tiebreak`` row below is what proves it.

The runner, the guarantees it enforces and the rules for running one live in
:mod:`_falsify`; read that first. Run it::

    uv run python apps/api/tests/tools/falsify_merchant_webhook_delivery.py
    uv run python apps/api/tests/tools/falsify_merchant_webhook_delivery.py -k retry
    uv run python apps/api/tests/tools/falsify_merchant_webhook_delivery.py --check-anchors

**Every row runs the same four files** — the integration drain, the retry unit
table, the signing unit tests and the worker's consumer tests — so the exact
``expect=`` sets below are comparable with each other and can see collateral
damage. All four together are 138 tests in about seventeen seconds; a narrower
``tests=`` per row would make the exactness vacuous.

## Two properties are deliberately not falsifiable here, and why

``decide_failure``'s ``Delivery.RECEIVED`` branch is **redundant today**: both
RECEIVED leaves (``ResponseTooLargeError``, ``ContentEncodingNotAllowedError``)
are also refusals, so the family branch under it reaches the same verdict.
Removing it changes no behaviour and no test would go red. It is kept for the
configuration it exists for — a RECEIVED leaf in the *unreachable* family,
which the family branch would retry — and ``received_in_the_wrong_family``
below moves one there to make the branch bite. The mutation therefore breaks
two things at once on purpose; that is what makes it a proof rather than a
tautology, and it is the same shape as ``core/outbound``'s deliberate
raw-read/encoding-refusal redundancy.

The **merchant-major lock ordering** in ``_merchant_major`` has no mutation
either: what it prevents is an AB/BA deadlock between two concurrent drainers,
which is timing-dependent and would make a flaky row here. It is argued in the
module docstring instead.
"""

from __future__ import annotations

import sys

from _falsify import REPO, SRC, Mutation, main

LIVE = "apps/api/tests/integration/test_merchant_webhook_delivery.py"
UNIT = "apps/api/tests/unit/test_merchant_webhook_retry.py"
SIGN = "apps/api/tests/unit/test_merchant_signing.py"
WORKER = "apps/worker/tests/test_consumer.py"

DELIVERY = SRC / "modules/merchants/webhook_delivery.py"
OUTCOME = SRC / "modules/merchants/webhook_outcome.py"
CONSUMER = REPO / "apps/worker/src/yupay_worker/consumer.py"
SHUTDOWN = REPO / "apps/worker/src/yupay_worker/shutdown.py"
RETRY = SRC / "modules/merchants/webhook_retry.py"
SIGNING = SRC / "modules/merchants/signing.py"
ERRORS = SRC / "core/outbound_errors.py"

#: Every row runs the same four files, so the blast radii below are comparable
#: with each other and an ``expect=`` set can see collateral damage. 138 tests
#: in about seventeen seconds; broader suites are the commit's gate, not this
#: file's job.
TESTS = (LIVE, UNIT, SIGN, WORKER)


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="no_id_tiebreak",
        breaks="two events from one transaction are claimed in an arbitrary order",
        edits=(
            (
                DELIVERY,
                "                # The tie-break the module docstring exists for.\n"
                "                MerchantWebhookDelivery.id,\n",
                "",
            ),
        ),
        tests=TESTS,
        expect=("test_two_events_from_one_transaction_are_delivered_in_enqueue_order",),
    ),
    Mutation(
        name="lock_the_hook_at_claim_time",
        breaks="one merchant's queue serialises onto a single drainer",
        edits=(
            (
                DELIVERY,
                ".with_for_update(skip_locked=True, of=MerchantWebhookDelivery)",
                ".with_for_update(skip_locked=True)",
            ),
        ),
        tests=TESTS,
        expect=("test_a_second_drainer_skips_locked_rows_and_takes_the_rest",),
    ),
    # ---- the worker loop. This queue shares a process with every retail
    # order's fulfilment, so its three properties are falsified here too.
    Mutation(
        name="shared_wake_event",
        breaks="one queue eats the other's wake-up and it waits out a full tick",
        edits=(
            (
                CONSUMER,
                "    wakes = tuple(asyncio.Event() for _ in queues)",
                "    wakes = (asyncio.Event(),) * len(queues)",
            ),
        ),
        tests=TESTS,
        expect=("test_run_gives_every_queue_its_own_task_and_its_own_wake_event",),
    ),
    Mutation(
        name="no_supervision",
        breaks="a dead queue leaves the process up, healthy-looking and one queue short",
        edits=(
            (
                CONSUMER,
                "    crashed = await shutdown.supervise(loops, stop=stop)",
                "    crashed = False\n    await stop.wait()",
            ),
        ),
        tests=TESTS,
        expect=("test_run_exits_non_zero_when_a_queue_loop_dies",),
    ),
    Mutation(
        name="strays_not_excluded",
        breaks="a stuck drain is waited on twice and shutdown reaches Docker's grace period",
        edits=(
            (
                CONSUMER,
                "    await shutdown.await_stray_tasks("
                "timeout=shutdown.remaining(deadline), exclude=loops)",
                "    await shutdown.await_stray_tasks(timeout=shutdown.remaining(deadline))",
            ),
        ),
        tests=TESTS,
        expect=("test_shutdown_spends_one_budget_and_not_two",),
    ),
    Mutation(
        name="no_truncation",
        breaks="an over-long response body reaches a length-bounded column",
        edits=((OUTCOME, "    return text[:limit]", "    return text"),),
        tests=TESTS,
        expect=(
            "test_a_long_outbound_error_message_is_clipped_too",
            "test_an_oversized_response_and_error_are_truncated_before_they_are_written",
        ),
    ),
    # ---- the claim predicate's three conjuncts, one row each.
    #
    # It had one row (``disabled_still_delivered``) for three conjuncts until
    # 2026-09-09. Nothing enumerates the rows nobody wrote, which is the gap
    # this harness cannot close on its own: it grades what somebody thought to
    # break. Counting the conjuncts of a predicate and checking each has a row
    # is the cheap manual version, and it is what found these two.
    Mutation(
        name="claim_ignores_the_status",
        breaks="a delivered or given-up row is claimed again and POSTed a second time",
        edits=((DELIVERY, '                MerchantWebhookDelivery.status == "pending",\n', ""),),
        tests=TESTS,
        expect=(
            "test_a_404_is_terminal",
            "test_a_blocked_address_is_recorded_as_a_policy_refusal_not_a_network_error",
            "test_the_batch_is_bounded_and_the_drain_reports_what_it_ran",
        ),
    ),
    Mutation(
        name="claim_ignores_the_backoff",
        breaks="a row that just failed is retried on the next tick, and the backoff means nothing",
        edits=(
            (DELIVERY, "                MerchantWebhookDelivery.next_attempt_at <= now(),\n", ""),
        ),
        tests=TESTS,
        expect=("test_a_row_whose_backoff_has_not_elapsed_is_not_claimed",),
    ),
    Mutation(
        name="disabled_still_delivered",
        breaks="a disabled hook keeps receiving deliveries",
        edits=((DELIVERY, "                MerchantWebhook.disabled_at.is_(None),\n", ""),),
        tests=TESTS,
        expect=("test_a_disabled_hook_stops_the_drain_and_re_enabling_resumes_it",),
    ),
    Mutation(
        name="no_savepoint",
        breaks="a poisoned row takes the whole batch down with it",
        edits=((DELIVERY, "            async with db.begin_nested():", "            if True:"),),
        tests=TESTS,
        expect=("test_a_poisoned_row_is_failed_and_the_rest_of_the_batch_still_lands",),
    ),
    Mutation(
        name="no_disabled_skip",
        breaks="rows claimed before an auto-disable are still POSTed after it",
        edits=((DELIVERY, "    if credentials is None:", "    if credentials is None and False:"),),
        tests=TESTS,
        expect=("test_a_sustained_failure_streak_disables_the_hook_and_emails_once",),
    ),
    Mutation(
        name="email_per_attempt",
        breaks="every failed attempt after the threshold sends another email",
        edits=(
            (DELIVERY, "    if credentials is None:", "    if credentials is None and False:"),
            (
                OUTCOME,
                "    if hook.failure_streak < threshold or hook.disabled_at is not None:",
                "    if hook.failure_streak < threshold:",
            ),
        ),
        tests=TESTS,
        expect=("test_a_sustained_failure_streak_disables_the_hook_and_emails_once",),
    ),
    Mutation(
        name="wrong_crypto_purpose",
        breaks="the webhook secret is read under the machine-API key's label",
        edits=(
            (
                DELIVERY,
                "purpose=crypto.PURPOSE_MERCHANT_WEBHOOK",
                "purpose=crypto.PURPOSE_MERCHANT_API_KEY",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_200_marks_the_row_delivered_and_logs_their_answer",
            "test_a_404_is_terminal",
            "test_a_429_honours_their_retry_after",
            "test_a_500_stays_pending_and_comes_back_later",
            "test_a_blocked_address_is_recorded_as_a_policy_refusal_not_a_network_error",
            "test_a_delivery_is_signed_with_the_documented_canonical_string",
            "test_a_disabled_hook_stops_the_drain_and_re_enabling_resumes_it",
            "test_a_long_outbound_error_message_is_clipped_too",
            "test_a_merchant_with_no_operator_is_disabled_without_an_email",
            "test_a_poisoned_row_is_failed_and_the_rest_of_the_batch_still_lands",
            "test_a_received_refusal_is_terminal_because_a_retry_would_re_deliver",
            "test_a_success_resets_the_streak_and_stamps_the_hook",
            "test_a_sustained_failure_streak_disables_the_hook_and_emails_once",
            "test_a_transport_failure_retries_and_records_the_type_not_a_status",
            "test_a_url_the_client_will_not_take_is_refused_before_anything_resolves",
            "test_an_oversized_response_and_error_are_truncated_before_they_are_written",
            "test_one_merchants_failures_do_not_stop_anothers_deliveries",
            "test_the_secret_and_the_signature_never_reach_the_log",
            "test_the_signature_is_keyed_by_the_secret_decrypted_at_send_time",
            "test_two_events_from_one_transaction_are_delivered_in_enqueue_order",
        ),
    ),
    Mutation(
        name="unsigned_delivery_id",
        breaks="the dedupe handle is a header only, worthless against a replay",
        edits=(
            (
                SIGNING,
                'return (f"{timestamp}\\n{delivery_id}\\n{event_type}\\n{body_digest(body)}").encode()',
                'return (f"{timestamp}\\n{event_type}\\n{body_digest(body)}").encode()',
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_delivery_is_signed_with_the_documented_canonical_string",
            "test_every_webhook_field_changes_the_signature[change1]",
            "test_every_webhook_field_is_fixed_width_or_cannot_carry_the_separator",
            "test_the_delivery_id_is_inside_the_signed_material",
            "test_the_webhook_canonical_message_is_the_documented_four_fields",
        ),
    ),
    Mutation(
        name="unvetted_event_type",
        breaks="an event type outside the vocabulary is signed and sent",
        edits=(
            (
                DELIVERY,
                "    if delivery.event_type not in EVENT_TYPES:",
                "    if delivery.event_type not in EVENT_TYPES and False:",
            ),
        ),
        tests=TESTS,
        expect=("test_an_unknown_event_type_is_refused_rather_than_signed",),
    ),
    Mutation(
        name="broken_counts_against_the_merchant",
        breaks="our own bug auto-disables a working endpoint",
        edits=(
            (
                RETRY,
                "    if isinstance(error, OutboundBrokenError):\n        return _TERMINAL_OURS\n",
                "",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_each_outbound_failure_gets_the_decision_its_taxonomy_implies[error2-terminal-False]",
            "test_every_leaf_of_the_taxonomy_is_decided_by_what_it_says_about_itself",
            "test_our_own_broken_attempt_never_touches_the_failure_streak",
            "test_our_own_bug_never_counts_toward_the_merchants_failure_budget",
        ),
    ),
    Mutation(
        name="received_in_the_wrong_family",
        breaks="a RECEIVED failure is retried, re-delivering an event they have",
        edits=(
            (
                RETRY,
                "    if error.delivery is Delivery.RECEIVED:\n"
                "        # They have it. A retry sends a second copy of an event they already\n"
                "        # processed — the one failure mode a retry policy must never cause.\n"
                "        return _TERMINAL_THEIRS\n",
                "",
            ),
            # ``ExchangeFailedError`` moved into the configuration the branch
            # above exists for: a RECEIVED answer whose family says "retry".
            (
                ERRORS,
                "    delivery: ClassVar[Delivery] = Delivery.UNKNOWN\n\n\nclass OutboundTimeoutError",
                "    delivery: ClassVar[Delivery] = Delivery.RECEIVED\n\n\nclass OutboundTimeoutError",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_received_delivery_is_never_retried_whatever_its_family",
            "test_every_leaf_of_the_taxonomy_is_decided_by_what_it_says_about_itself",
        ),
    ),
    Mutation(
        name="unfamilied_leaf_blamed_on_the_merchant",
        breaks="a leaf nobody classified counts against a merchant's endpoint",
        edits=(
            (
                RETRY,
                "    # An ``OutboundError`` in neither family cannot exist today (a test walks\n"
                "    # the taxonomy to keep it that way). If one ever does, blame ourselves\n"
                "    # rather than a merchant: a leaf nobody classified is our omission.\n"
                "    return _TERMINAL_OURS",
                "    return _TERMINAL_THEIRS",
            ),
        ),
        tests=TESTS,
        expect=("test_a_leaf_in_neither_family_is_blamed_on_us_not_on_the_merchant",),
    ),
    Mutation(
        name="retry_after_not_ascii_checked",
        breaks="a non-ASCII digit header raises and fails a delivery terminally",
        edits=(
            (
                RETRY,
                "    if candidate.isascii() and candidate.isdigit():",
                "    if candidate.isdigit():",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_non_ascii_digit_header_never_escapes_as_an_exception[\\u0661\\u0662\\u0660]",
            "test_a_non_ascii_digit_header_never_escapes_as_an_exception[\\u0662]",
            "test_a_non_ascii_digit_header_never_escapes_as_an_exception[\\xb2]",
            "test_an_unusable_retry_after_falls_back_to_the_backoff[\\u0661\\u0662\\u0660]",
            "test_an_unusable_retry_after_falls_back_to_the_backoff[\\xb2]",
        ),
    ),
    Mutation(
        name="every_4xx_retried",
        breaks="a 404 is retried for hours instead of being given up on",
        edits=(
            (
                RETRY,
                "    retryable = status_code in _RETRYABLE_CLIENT_STATUSES or status_code >= 500",
                "    retryable = status_code >= 400",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_404_is_terminal",
            "test_a_4xx_or_a_redirect_is_terminal[400]",
            "test_a_4xx_or_a_redirect_is_terminal[401]",
            "test_a_4xx_or_a_redirect_is_terminal[403]",
            "test_a_4xx_or_a_redirect_is_terminal[404]",
            "test_a_4xx_or_a_redirect_is_terminal[410]",
            "test_a_4xx_or_a_redirect_is_terminal[422]",
        ),
    ),
    Mutation(
        name="retry_after_unclamped",
        breaks="a merchant's own header schedules the retry, unbounded",
        edits=(
            (
                RETRY,
                "    return min(max(seconds, RETRY_AFTER_FLOOR_SECONDS), BACKOFF_CAP_SECONDS)",
                "    return seconds",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_retry_after_in_the_past_is_floored_rather_than_ignored",
            "test_a_retry_after_of_zero_is_floored_so_it_cannot_become_a_hot_loop",
            "test_an_enormous_retry_after_is_capped",
        ),
    ),
    Mutation(
        name="backoff_off",
        breaks="a failed row is due again immediately and spins on the next tick",
        edits=(
            (
                RETRY,
                "    return min(BACKOFF_BASE_SECONDS * (2.0**doublings), BACKOFF_CAP_SECONDS)",
                "    return 0.0",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_500_stays_pending_and_comes_back_later",
            "test_backoff_doubles_from_the_base_and_stops_at_the_cap",
            "test_backoff_of_a_first_attempt_is_never_zero",
        ),
    ),
)


if __name__ == "__main__":
    sys.exit(main(MUTATIONS, description=__doc__))
