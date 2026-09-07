#!/usr/bin/env python
"""Mutation harness for the merchant webhook **delivery drain** (M3a, Task 4).

Same contract as its two siblings: break one property at a time and check the
named test actually goes red. A test that stays green under a mutation is a
test that would not have noticed the regression, and this file exists because
one of them already did that here — the first version of the enqueue-order
test inserted its two rows in id order, so Postgres returned them in physical
order and the test passed with the ``ORDER BY`` tie-break deleted. It now
inserts them in the **opposite** order to their ids, and the ``no_id_tiebreak``
row below is what proves it.

Run it::

    uv run python apps/api/tests/tools/falsify_merchant_webhook_delivery.py
    uv run python apps/api/tests/tools/falsify_merchant_webhook_delivery.py -k retry

**Run nothing else against this worktree while this is running.** It edits
source files in place, so any concurrently running suite imports whatever
mutation happens to be applied at that moment and fails for reasons that have
nothing to do with it — a failure whose signature is indistinguishable from a
real regression (see ``falsify_merchant_webhook_events.py``'s docstring for
the worked example that cost an afternoon).

Sources are restored from a copy taken before the edit, in a ``finally``.
Never ``git checkout`` — several agents share this worktree. pytest runs in its
own process group, killed as a group in a ``finally``: on SIGINT the group dies
and the tree comes back byte-identical; on SIGKILL neither runs and the tree is
left mutated, which is the reason not to ``kill -9`` this script.

## One property is deliberately not falsifiable here, and why

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
LIVE = "apps/api/tests/integration/test_merchant_webhook_delivery.py"
UNIT = "apps/api/tests/unit/test_merchant_webhook_retry.py"
SIGN = "apps/api/tests/unit/test_merchant_signing.py"

DELIVERY = SRC / "modules/merchants/webhook_delivery.py"
RETRY = SRC / "modules/merchants/webhook_retry.py"
SIGNING = SRC / "modules/merchants/signing.py"
ERRORS = SRC / "core/outbound_errors.py"

#: ``FAILED apps/.../test_x.py::test_name[param] - AssertionError: …``.
_FAILED_LINE = re.compile(r"^FAILED\s+\S+?\.py::(?P<name>.+?)(?:\s+-\s.*)?$")


@dataclass(frozen=True)
class Mutation:
    """One way to break the drain, and the tests that must notice.

    Attributes:
        name: How the row is reported.
        breaks: What property this removes, for the report.
        edits: ``(path, old, new)`` triples. Each must change its file.
        tests: Test ids or files to run.
        expect: Test names that must be among the failures.
    """

    name: str
    breaks: str
    edits: tuple[tuple[Path, str, str], ...]
    tests: tuple[str, ...]
    expect: tuple[str, ...] = ()


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
        tests=(f"{LIVE}::test_two_events_from_one_transaction_are_delivered_in_enqueue_order",),
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
        tests=(f"{LIVE}::test_a_second_drainer_skips_locked_rows_and_takes_the_rest",),
        expect=("test_a_second_drainer_skips_locked_rows_and_takes_the_rest",),
    ),
    Mutation(
        name="no_truncation",
        breaks="an over-long response body reaches a length-bounded column",
        edits=((DELIVERY, "    return text[:limit]", "    return text"),),
        tests=(
            f"{LIVE}::test_an_oversized_response_and_error_are_truncated_before_they_are_written",
            f"{LIVE}::test_a_long_outbound_error_message_is_clipped_too",
        ),
        expect=(
            "test_an_oversized_response_and_error_are_truncated_before_they_are_written",
            "test_a_long_outbound_error_message_is_clipped_too",
        ),
    ),
    Mutation(
        name="disabled_still_delivered",
        breaks="a disabled hook keeps receiving deliveries",
        edits=((DELIVERY, "                MerchantWebhook.disabled_at.is_(None),\n", ""),),
        tests=(f"{LIVE}::test_a_disabled_hook_stops_the_drain_and_re_enabling_resumes_it",),
        expect=("test_a_disabled_hook_stops_the_drain_and_re_enabling_resumes_it",),
    ),
    Mutation(
        name="no_savepoint",
        breaks="a poisoned row takes the whole batch down with it",
        edits=((DELIVERY, "            async with db.begin_nested():", "            if True:"),),
        tests=(f"{LIVE}::test_a_poisoned_row_is_failed_and_the_rest_of_the_batch_still_lands",),
        expect=("test_a_poisoned_row_is_failed_and_the_rest_of_the_batch_still_lands",),
    ),
    Mutation(
        name="no_disabled_skip",
        breaks="rows claimed before an auto-disable are still POSTed after it",
        edits=((DELIVERY, "    if credentials is None:", "    if credentials is None and False:"),),
        tests=(f"{LIVE}::test_a_sustained_failure_streak_disables_the_hook_and_emails_once",),
        expect=("test_a_sustained_failure_streak_disables_the_hook_and_emails_once",),
    ),
    Mutation(
        name="email_per_attempt",
        breaks="every failed attempt after the threshold sends another email",
        edits=(
            (DELIVERY, "    if credentials is None:", "    if credentials is None and False:"),
            (
                DELIVERY,
                "    if hook.failure_streak < threshold or hook.disabled_at is not None:",
                "    if hook.failure_streak < threshold:",
            ),
        ),
        tests=(f"{LIVE}::test_a_sustained_failure_streak_disables_the_hook_and_emails_once",),
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
        tests=(f"{LIVE}::test_a_delivery_is_signed_with_the_documented_canonical_string",),
        expect=("test_a_delivery_is_signed_with_the_documented_canonical_string",),
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
        tests=(SIGN, f"{LIVE}::test_a_delivery_is_signed_with_the_documented_canonical_string"),
        expect=(
            "test_the_delivery_id_is_inside_the_signed_material",
            "test_a_delivery_is_signed_with_the_documented_canonical_string",
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
        tests=(f"{LIVE}::test_an_unknown_event_type_is_refused_rather_than_signed",),
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
        tests=(UNIT, f"{LIVE}::test_our_own_broken_attempt_never_touches_the_failure_streak"),
        expect=(
            "test_our_own_bug_never_counts_toward_the_merchants_failure_budget",
            "test_our_own_broken_attempt_never_touches_the_failure_streak",
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
        tests=(UNIT,),
        expect=("test_a_received_delivery_is_never_retried_whatever_its_family",),
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
        tests=(UNIT, f"{LIVE}::test_a_404_is_terminal"),
        expect=("test_a_4xx_or_a_redirect_is_terminal", "test_a_404_is_terminal"),
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
        tests=(UNIT,),
        expect=(
            "test_an_enormous_retry_after_is_capped",
            "test_a_retry_after_of_zero_is_floored_so_it_cannot_become_a_hot_loop",
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
        tests=(UNIT, f"{LIVE}::test_a_500_stays_pending_and_comes_back_later"),
        expect=(
            "test_backoff_of_a_first_attempt_is_never_zero",
            "test_a_500_stays_pending_and_comes_back_later",
        ),
    ),
)


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
    # Own process group, killed as a group in ``finally`` — the shape d12927c
    # settled on after three pytest children were found alive two hours later,
    # competing for the Postgres the rest of the suite uses.
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
    failures = [
        match.group("name") for line in stdout.splitlines() if (match := _FAILED_LINE.match(line))
    ]
    if process.returncode == 0:
        return "UNFALSIFIED — the suite stayed green", []
    missing = [name for name in mutation.expect if not any(name in f for f in failures)]
    if missing:
        return f"failed, but not on {', '.join(missing)}", failures
    return "failed as expected", failures


def main() -> int:
    """Run every mutation (or those matching ``-k``) and print a table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-k", dest="pattern", default="", help="substring of the mutation name")
    parser.add_argument("--list", action="store_true", help="print the mutations and exit")
    args = parser.parse_args()

    chosen = [m for m in MUTATIONS if args.pattern in m.name]
    if args.list:
        for mutation in chosen:
            print(f"{mutation.name:36} {mutation.breaks}")
        return 0

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
            verdict, _failures = _run(mutation)
        finally:
            _restore(backups)
        rows.append((mutation.name, verdict))
        print(f"{mutation.name:36} {verdict}", flush=True)

    print("\n--- summary ---")
    unfalsified = [
        name for name, verdict in rows if verdict.startswith(("UNFALSIFIED", "failed, but"))
    ]
    for name, verdict in rows:
        print(f"{name:36} {verdict}")
    if unfalsified:
        print(f"\n{len(unfalsified)} mutation(s) not falsified: {', '.join(unfalsified)}")
        return 1
    print(f"\nall {len(rows)} mutations falsified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
