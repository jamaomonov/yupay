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
  database, so ``FulfillmentTask.order_id == order.id`` could be deleted with
  the whole integration selection still green (measured: 679 passed, 0
  failed). ``stall_ignores_the_order`` plus the two-merchant test it reddens
  are what stop one reseller's stall from publishing ``fulfillment_delayed``
  on everybody else's healthy orders — this task's own harm, inverted.

**Two rows here exist because they were found vacuous first.**
``stall_ignores_the_item_state`` reported ``UNFALSIFIED`` until a two-**line**
order gave the item half something to be wrong about, and
``stall_ignores_the_order`` was added after a review deleted that one line and
watched nothing fail. Both are the same lesson: a mutation that grades nothing
is worse than no row, and the only fix is the test shape that reaches the half.

Run it::

    uv run python apps/api/tests/tools/falsify_merchant_stall.py
    uv run python apps/api/tests/tools/falsify_merchant_stall.py -k retail
    uv run python apps/api/tests/tools/falsify_merchant_stall.py --check-anchors

**Run nothing else against this worktree while this is running.** It edits
source files in place, so any concurrently running suite imports whatever
mutation happens to be applied at that moment and fails for reasons that have
nothing to do with it.

Sources are restored from a copy taken before the edit, in a ``finally``.
Never ``git checkout`` — several agents share this worktree. pytest runs in
its own process group, killed as a group in a ``finally``: on SIGINT the group
dies and the tree comes back byte-identical; on SIGKILL neither runs and the
tree is left mutated, which is the reason not to ``kill -9`` this script.

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
STALL_TESTS = "apps/api/tests/integration/test_merchant_order_stall.py"
TABLE_TESTS = "apps/api/tests/unit/test_merchant_failure_reason.py"

SAGA = SRC / "modules/fulfillment/service.py"
STALL = SRC / "modules/fulfillment/stall.py"
STATUS = SRC / "modules/merchants/order_status.py"

#: ``FAILED apps/.../test_x.py::test_name[param] - AssertionError: …``.
_FAILED_LINE = re.compile(r"^FAILED\s+\S+?\.py::(?P<name>.+?)(?:\s+-\s.*)?$")

#: Every row runs the same two files, so the blast radii below are comparable
#: with each other. Broader suites are the commit's gate, not this file's job.
TESTS = (STALL_TESTS, TABLE_TESTS)


@dataclass(frozen=True)
class Mutation:
    """One way to break the stall, and the tests that must notice.

    Attributes:
        name: How the row is reported.
        breaks: What property this removes, for the report.
        edits: ``(path, old, new)`` triples. Each must change its file.
        tests: Test ids or files to run.
        expect: The **exact** set of tests this mutation must redden — not a
            subset. Equality is the point: a sibling harness asserted only
            membership, and a row that reddened nine tests where three were
            expected passed silently for two review rounds. Fill it in with
            ``--record``.
    """

    name: str
    breaks: str
    edits: tuple[tuple[Path, str, str], ...]
    tests: tuple[str, ...]
    expect: tuple[str, ...] = ()


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
        expect=(
            "test_the_failure_reason_table[stalled and closed-failed-in_progress-True-refunded9-order_failed]",
            "test_the_failure_reason_table[stalled and failed-fulfilling-failed-True-refunded10-fulfillment_failed]",
            "test_the_failure_reason_table[stalled and refunded-fulfilling-failed-True-refunded11-fulfillment_failed_refunded]",
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
        expect=(
            "test_the_failure_reason_table[stalled and failed-fulfilling-failed-True-refunded10-fulfillment_failed]",
            "test_the_failure_reason_table[stalled and refunded-fulfilling-failed-True-refunded11-fulfillment_failed_refunded]",
        ),
    ),
    # ---- the predicate's two halves
    Mutation(
        name="stall_ignores_the_order",
        breaks="one reseller's stall publishes fulfillment_delayed on everybody's orders",
        edits=((STALL, "                FulfillmentTask.order_id == order.id,\n", ""),),
        tests=TESTS,
        expect=("test_one_merchants_stall_does_not_delay_another_merchants_order",),
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
        edits=(
            (
                STALL,
                "    if not any(item.fulfillment_state in UNSETTLED_ITEM_STATES "
                "for item in order.items):\n        return False\n",
                "",
            ),
        ),
        tests=TESTS,
        expect=("test_a_settled_order_costs_no_stall_query",),
    ),
)


def _check_anchors(chosen: list[Mutation]) -> int:
    """Report every stale anchor at once, in seconds, without touching the tree.

    The whole run aborts on the **first** stale anchor — deliberately, because
    a harness that carries on after one is a harness reporting on a tree it did
    not mutate. That is right and it is also slow: each discovery costs a
    pytest run. This finds all of them in about a second, and it is the
    cheapest thing to run after any refactor near the predicate.

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
                stale.append(f"{mutation.name:38} {path.name}  {old.splitlines()[0][:60]!r}")
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
            print(f"{mutation.name:38} {mutation.breaks}")
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
        print(f"{mutation.name:38} {verdict}", flush=True)
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
        print(f"{name:38} {verdict}")
    if unfalsified:
        print(f"\n{len(unfalsified)} mutation(s) not falsified: {', '.join(unfalsified)}")
        return 1
    print(f"\nall {len(rows)} mutations falsified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
