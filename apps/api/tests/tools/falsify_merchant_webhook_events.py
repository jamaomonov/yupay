#!/usr/bin/env python
"""Mutation harness for the merchant webhook **producer** (M3a, Task 3).

Every property in ``merchants/webhooks.py`` and in the status-change seam is
only as good as the test that goes red when it is removed. This script breaks
each one in turn and checks that the named tests actually fail — the
difference between "the suite passes" and "the suite would notice".

Run it::

    uv run python apps/api/tests/tools/falsify_merchant_webhook_events.py
    uv run python apps/api/tests/tools/falsify_merchant_webhook_events.py -k notify

Committed for the reason ``falsify_outbound.py`` is: a falsification result
nobody can re-run is a claim, not evidence. It inherits that file's two
lessons — every mutation asserts it **changed the file** before the suite
runs, and a green suite under a mutation is reported ``UNFALSIFIED``, loudly —
and it found the same class of problem once during Task 3: the first attempt
at the ``url``-snapshot mutation was *equivalent to the original code*
(re-reading the hook's URL at enqueue time yields the same value it already
had), so it could not have failed. The mutation that does bite is the
plausible regression on the **config** path — a well-meaning "keep the log
tidy" UPDATE, which is exactly what joining the log onto ``merchant_webhooks``
would amount to.

**Run nothing else against this worktree while this is running.** It edits
source files in place, so any concurrently running suite imports whatever
mutation happens to be applied at that moment and fails for reasons that have
nothing to do with it. That is not hypothetical: running this alongside an
``-n auto`` integration pass produced a ``PendingRollbackError`` in
``test_an_enqueue_that_raises_does_not_roll_back_the_order`` — the exact
signature the ``no_savepoint`` mutation is designed to cause, in a worker that
had imported ``webhooks.py`` mid-mutation. The banner below says so on every
run.

Sources are restored from a copy taken before the edit, in a ``finally``.
Never ``git checkout`` — several agents share this worktree. pytest runs in
its own process group, killed as a group in a ``finally`` (the shape
``falsify_outbound.py`` took in d12927c).

What that covers, measured rather than assumed: on **SIGINT** — Ctrl-C, an
agent stopped — the group is killed and the worktree is restored
byte-identical, verified by hashing the file before, during and after an
interrupted run (mutated mid-run, hash equal after, zero surviving children,
no leftover backup directory). On **SIGKILL** nothing in-process runs, so that
case still leaves a mutated worktree; there is no in-process answer to it, and
the mitigation is to not ``kill -9`` this script.
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
EVENTS = "apps/api/tests/integration/test_merchant_webhook_events.py"

HOOKS = SRC / "modules/merchants/webhooks.py"
DEPOSIT = SRC / "modules/merchants/deposit.py"
ADMIN = SRC / "modules/merchants/admin.py"
ORDERS = SRC / "modules/orders/service.py"
FULFILMENT = SRC / "modules/fulfillment/service.py"

#: ``FAILED apps/.../test_x.py::test_name[param] - AssertionError: …``.
_FAILED_LINE = re.compile(r"^FAILED\s+\S+?\.py::(?P<name>.+?)(?:\s+-\s.*)?$")


@dataclass(frozen=True)
class Mutation:
    """One way to break the producer, and the tests that must notice.

    Attributes:
        name: How the row is reported.
        breaks: What property this removes, for the report.
        edits: ``(path, old, new)`` triples. Each must change its file.
        tests: Test ids to run.
        expect: Test names that must be among the failures.
    """

    name: str
    breaks: str
    edits: tuple[tuple[Path, str, str], ...]
    tests: tuple[str, ...]
    expect: tuple[str, ...] = ()


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="disabled_ignored",
        breaks="a disabled hook still collects rows nobody will deliver",
        edits=((HOOKS, "                MerchantWebhook.disabled_at.is_(None),\n", ""),),
        tests=(f"{EVENTS}::test_a_disabled_webhook_enqueues_nothing",),
        expect=("test_a_disabled_webhook_enqueues_nothing",),
    ),
    Mutation(
        name="no_savepoint",
        breaks="a failed insert poisons the session instead of rolling back alone",
        edits=((HOOKS, "        async with db.begin_nested():\n", "        if True:\n"),),
        tests=(f"{EVENTS}::test_an_enqueue_that_raises_does_not_roll_back_the_order",),
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
        tests=(f"{EVENTS}::test_a_rolled_back_transaction_leaves_no_row_and_fires_no_notify",),
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
        tests=(f"{EVENTS}::test_the_channel_name_is_the_one_task_four_listens_on",),
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
        tests=(f"{EVENTS}::test_delivering_the_order_enqueues_delivered_and_never_the_code",),
        expect=("test_delivering_the_order_enqueues_delivered_and_never_the_code",),
    ),
    Mutation(
        name="replay_announced",
        breaks="a replayed credit announces money that did not move",
        edits=((DEPOSIT, "    if not replayed:\n", "    if True:\n"),),
        tests=(f"{EVENTS}::test_a_replayed_credit_enqueues_nothing_the_second_time",),
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
        tests=(f"{EVENTS}::test_a_retail_delivery_still_publishes_only_order_delivered",),
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
        tests=(f"{EVENTS}::test_delivering_the_order_enqueues_delivered_and_never_the_code",),
        expect=("test_delivering_the_order_enqueues_delivered_and_never_the_code",),
    ),
    Mutation(
        name="paid_not_hooked",
        breaks="the status a merchant order is born in is never announced",
        edits=(
            (ORDERS, "    await on_order_status_changed(db, order, publish_realtime=False)\n", ""),
        ),
        tests=(
            f"{EVENTS}::test_a_merchant_order_enqueues_paid_and_fulfilling_with_an_exact_payload",
        ),
        expect=("test_a_merchant_order_enqueues_paid_and_fulfilling_with_an_exact_payload",),
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
        tests=(
            f"{EVENTS}::"
            "test_the_url_is_snapshotted_at_enqueue_and_a_later_move_does_not_rewrite_it",
        ),
        expect=("test_the_url_is_snapshotted_at_enqueue_and_a_later_move_does_not_rewrite_it",),
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
    # Own process group, killed as a group in ``finally`` — the same shape
    # ``falsify_outbound.py`` took in d12927c after three of its pytest children
    # were found alive two hours later, competing for the Postgres and Redis the
    # rest of the suite uses.
    #
    # None of *these* mutations hangs on purpose, so the timeout path is
    # unlikely. The interrupt path is what matters here and it is worse: under
    # SIGKILL neither this ``finally`` nor ``_restore``'s runs, so an
    # interrupted run leaves both an orphaned pytest **and a mutated worktree**.
    # Killing the group closes the half that is closable.
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
            print(f"{mutation.name:30} {mutation.breaks}")
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
        print(f"{mutation.name:30} {verdict}", flush=True)

    print("\n--- summary ---")
    unfalsified = [
        name for name, verdict in rows if verdict.startswith(("UNFALSIFIED", "failed, but"))
    ]
    for name, verdict in rows:
        print(f"{name:30} {verdict}")
    if unfalsified:
        print(f"\n{len(unfalsified)} mutation(s) not falsified: {', '.join(unfalsified)}")
        return 1
    print(f"\nall {len(rows)} mutations falsified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
