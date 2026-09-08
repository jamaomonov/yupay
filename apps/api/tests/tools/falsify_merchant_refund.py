#!/usr/bin/env python
"""Mutation harness for the automatic deposit refund (M3b, Task 3).

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

Sources are restored from a copy taken before the edit, in a ``finally``.
Never ``git checkout`` — several agents share this worktree. pytest runs in
its own process group, killed as a group in a ``finally``: on SIGINT the group
dies and the tree comes back byte-identical; on SIGKILL neither runs and the
tree is left mutated, which is the reason not to ``kill -9`` this script.

## Two properties are deliberately not falsifiable here, and why

**"A frozen merchant is still refunded"** has no code to delete — the refund
simply never reads ``merchants.status``. Its mutation therefore *adds* the
check somebody would plausibly add, which is the only honest way to falsify an
absence.

**The concurrent-drain interleave** (``test_two_drainers_on_two_connections_refund_once``)
is guarded by a Postgres unique index, not by any line in this repo. Removing
``wallet.service.post``'s IntegrityError arm would break a hundred unrelated
tests and prove nothing about this one; the test earns its place by using two
real connections rather than by a row here.
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

REFUND = SRC / "modules/merchants/refund.py"
DEPOSIT = SRC / "modules/merchants/deposit.py"
STATUS = SRC / "modules/merchants/order_status.py"
SAGA = SRC / "modules/fulfillment/service.py"

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
        expect: Test names that must be among the failures.
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
        expect=("test_a_failure_that_did_not_return_our_money_refunds_nothing",),
    ),
    Mutation(
        name="no_merchant_gate",
        breaks="every retail order that runs the warehouse dry reaches the refund",
        edits=(
            (
                SAGA,
                "    if order.merchant_id is None:\n        return\n    order_id = order.id",
                "    order_id = order.id",
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
        name="refund_inside_the_savepoint",
        breaks="a crash in the refund is laundered into a permanent UNKNOWN by the crash arm",
        edits=(
            (
                SAGA,
                "            async with db.begin_nested():\n"
                "                await process_task(db, task_id=task_id)\n",
                "            async with db.begin_nested():\n"
                "                await process_task(db, task_id=task_id)\n"
                "                await _settle_merchant_deposit(db, task_id=task_id)\n",
            ),
            (
                SAGA,
                "        await _settle_merchant_deposit(db, task_id=task_id)\n"
                "        settled.add(order_id)",
                "        settled.add(order_id)",
            ),
        ),
        tests=(LIVE,),
        expect=("test_an_unexpected_refund_crash_never_reaches_the_unknown_crash_arm",),
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
    # ---- the amount
    Mutation(
        name="amount_from_the_order_line",
        breaks="the refund follows a list price that moved instead of what we charged",
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
        expect=("test_the_refund_is_what_we_charged_not_what_the_line_says_now",),
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
            "test_a_returned_failure_returns_the_charge_to_the_deposit",
            "test_the_two_keys_for_one_order_are_different_strings",
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
        expect=("test_an_order_support_already_settled_is_not_refunded_again",),
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
                "        return REASON_FULFILLMENT_REFUNDED if refunded > 0 else REASON_FULFILLMENT_FAILED",
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
                "        return REASON_FULFILLMENT_REFUNDED if refunded > 0 else REASON_FULFILLMENT_FAILED",
                "        return REASON_FULFILLMENT_REFUNDED",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_failed_refund_leaves_the_order_saying_a_human_is_deciding",
            "test_a_failure_that_did_not_return_our_money_refunds_nothing",
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
        expect=("test_a_failure_that_did_not_return_our_money_refunds_nothing",),
    ),
    Mutation(
        name="no_alert_when_the_refund_fails",
        breaks="a refund that could not post is a log line nobody reads",
        edits=(
            (
                SAGA,
                "        _dispatch_alert(\n"
                "            _alert_merchant_refund_failed(task_id=task_id, order_id=order_id, error=detail)\n"
                "        )\n",
                "",
            ),
        ),
        tests=(LIVE,),
        expect=(
            "test_a_refund_failure_leaves_the_task_refundable",
            "test_an_order_with_no_charge_refunds_nothing_and_calls_a_human",
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
            print(f"{mutation.name:44} {mutation.breaks}")
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
        print(f"{mutation.name:44} {verdict}", flush=True)

    print("\n--- summary ---")
    unfalsified = [
        name
        for name, verdict in rows
        if verdict.startswith(("UNFALSIFIED", "failed, but", "TIMED OUT"))
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
