#!/usr/bin/env python
"""The runner every ``falsify_*.py`` harness in this directory shares.

A harness is a table of :class:`Mutation` rows plus one call to :func:`main`.
Everything else — applying an edit, restoring the tree, running pytest,
grading the result — lives here, because it used to live in five copies and
the copies drifted. Two of them were hardened during M3b (an **exact** expected
red set per row, and ``--check-anchors``); the other three were not, and one
of those three carried a mutation that had been landing on the wrong line for
a week. Copying the fix into three more files would have re-created the thing
that produced the bug.

## The three properties this runner enforces, and what each one cost

**An edit must change its file.** ``str.replace`` that matches nothing is a
silent no-op, and a harness reporting GREEN from one is worse than no harness.
Two rows of the first outbound table were like this: one edited a file the code
had moved out of, and both were silent.

**An anchor must match exactly once.** This is the newer lesson and the
subtler one. ``str.replace`` matches **substrings, not lines**, so an anchor
that begins with leading whitespace can match a *more-indented* line anywhere
in the file — the four spaces of ``"    if not replayed:"`` are a substring of
the eight spaces of ``"        if not replayed:"``, starting at offset 4. It is
not about duplicate lines: the two lines were different lines, at different
indents, guarding different things. The events harness's ``replay_announced``
anchored on the four-space form and, once M3b added an eight-space one earlier
in the same file, silently mutated the wrong branch — a branch its test never
enters, so the row reported a *surviving mutation*: a false alarm, not a quiet
pass. :func:`_apply` therefore refuses an anchor with a match count other than
one, and ``--check-anchors`` reports every such anchor without running pytest.
When an anchor is ambiguous the fix is to widen it — add the line below it,
usually — not to trust the first match.

**The expected red set is exact, not a subset.** A row that says "these three
tests go red" and reddens nine is grading something other than what it says.
That happened: a refund row reddened nine where it declared three and survived
two review rounds, because the assertion was membership. Equality catches it.
Record the set from an observed run with ``--record``; do not write it from
reading the tests.

## Running one

::

    uv run python apps/api/tests/tools/falsify_<name>.py
    uv run python apps/api/tests/tools/falsify_<name>.py -k some_row
    uv run python apps/api/tests/tools/falsify_<name>.py --check-anchors
    uv run python apps/api/tests/tools/falsify_<name>.py --record

**Run nothing else against this worktree while one is running**, and never two
at once. They edit source files in place, so any concurrently running suite
imports whatever mutation happens to be applied at that moment and fails for
reasons that have nothing to do with it — a failure whose signature is
indistinguishable from a real regression. That is not hypothetical: an
``-n auto`` integration pass beside one of these produced a
``PendingRollbackError`` matching the exact signature the ``no_savepoint``
mutation is built to cause, in a worker that had imported the module
mid-mutation.

Sources are restored from a copy taken before the edit, in a ``finally``.
Never ``git checkout`` — several agents share this worktree. pytest runs in its
own process group, killed as a group in a ``finally``: on **SIGINT** the group
dies and the tree comes back byte-identical (measured by hashing a file before,
during and after an interrupted run — mutated mid-run, hash equal after, zero
surviving children, no leftover backup directory). On **SIGKILL** neither the
``finally`` nor :func:`_restore` runs, so the tree is left mutated; there is no
in-process answer to that, and the mitigation is to not ``kill -9`` a harness.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Repository root. ``_falsify.py`` sits beside the harnesses, so the two
#: agree on the depth: ``tools`` → ``tests`` → ``api`` → ``apps`` → repo.
REPO = Path(__file__).resolve().parents[4]
SRC = REPO / "apps/api/src/yupay"

#: ``FAILED apps/.../test_x.py::test_name[param] - AssertionError: …``. Split
#: on ``::`` instead and a parametrised IPv6 address (``[fec0::1]``) reports
#: itself as ``1]`` — which is how the first outbound run said a mutation
#: "failed, but not on" a test it had in fact failed on.
_FAILED_LINE = re.compile(r"^FAILED\s+\S+?\.py::(?P<name>.+?)(?:\s+-\s.*)?$")


@dataclass(frozen=True)
class Mutation:
    """One way to break a property, and the tests that must notice.

    Attributes:
        name: How the row is reported.
        breaks: What property this removes, for the report.
        edits: ``(path, old, new)`` triples, applied in order. Each ``old``
            must occur **exactly once** in the file as it stands when the edit
            runs — see this module's docstring for why "once" and not "at
            least once".
        tests: Test files, or ``file::name`` ids, to run. Prefer whole files:
            ``expect`` is an exact set, so a row that runs only the test it
            names cannot detect collateral damage, which is most of what the
            exact set is for.
        expect: The **exact** set of tests this mutation must redden — not a
            subset. Fill it in with ``--record`` from an observed run. Empty
            is meaningful only on a ``hang_is_failure`` row, where the
            expected outcome is a hang rather than a failure.
        timeout: Seconds to wait for pytest.
        hang_is_failure: Whether a timeout counts as the expected failure. True
            for a mutation that removes a deadline: the client then waits
            forever, which *is* the failure the deadline prevents.
        extra_args: Extra pytest arguments for this row.
    """

    name: str
    breaks: str
    edits: tuple[tuple[Path, str, str], ...]
    tests: tuple[str, ...]
    expect: tuple[str, ...] = ()
    timeout: int = 900
    hang_is_failure: bool = False
    extra_args: Sequence[str] = field(default_factory=tuple)


def check_anchors(chosen: Sequence[Mutation]) -> int:
    """Report every unusable anchor at once, in seconds, without touching the tree.

    A real run aborts on the **first** bad anchor — deliberately, because a
    harness that carries on after one is a harness reporting on a tree it did
    not mutate. That is right and it is also slow: each discovery costs a
    pytest round trip, and five accumulated in a single round on M3b while the
    code moved under them. This finds all of them at once, and it is the
    cheapest thing to run after any refactor near the code a harness anchors
    into.

    Two failures are reported, and the second is the one that hides:

    * ``STALE`` — the anchor matches nothing. The code moved.
    * ``AMBIGUOUS`` — the anchor matches more than once as a **substring**.
      Usually because it starts with leading whitespace and a more-indented
      line elsewhere in the file contains it. ``str.replace`` would take the
      first match, which is not necessarily the one the row names.

    Args:
        chosen: The rows to check.

    Returns:
        A process exit code: non-zero if any anchor is unusable.
    """
    cache: dict[Path, str] = {}
    bad: list[str] = []
    for mutation in chosen:
        edited: dict[Path, str] = {}
        for path, old, _new in mutation.edits:
            source = edited.get(path) or cache.setdefault(path, path.read_text())
            found = source.count(old)
            if found != 1:
                label = "STALE    " if found == 0 else f"AMBIGUOUS×{found}"
                head = old.splitlines()[0] if old else old
                bad.append(f"{label}  {mutation.name:44} {path.name}  {head[:64]!r}")
                continue
            edited[path] = source.replace(old, _new, 1)
    for row in bad:
        print(row)
    print(f"\n{len(bad)} unusable anchor(s) across {len(chosen)} rows")
    return 1 if bad else 0


def _apply(mutation: Mutation, backups: dict[Path, Path]) -> None:
    """Apply every edit, insisting each one matches exactly once.

    Args:
        mutation: The row to apply.
        backups: Path → pre-edit copy, extended in place so the caller can
            restore whatever was touched before an exception.

    Raises:
        SystemExit: If an anchor matches no line, or more than one.
    """
    for path, old, new in mutation.edits:
        if path not in backups:
            copy = Path(tempfile.mkdtemp(prefix="falsify-")) / path.name
            shutil.copy2(path, copy)
            backups[path] = copy
        source = path.read_text()
        found = source.count(old)
        if found == 0:
            raise SystemExit(
                f"{mutation.name}: the edit changed nothing in {path.name}. "
                "A str.replace that matches nothing is a silent no-op, and a "
                "harness that reports GREEN from one is worse than no harness."
            )
        if found > 1:
            raise SystemExit(
                f"{mutation.name}: the anchor matches {found} places in {path.name}, "
                "so str.replace would pick the first — which is not necessarily "
                "the one this row names. An anchor that starts with leading "
                "whitespace matches any more-indented line containing it. Widen "
                "the anchor until it matches once."
            )
        path.write_text(source.replace(old, new, 1))


def _restore(backups: dict[Path, Path]) -> None:
    """Put every mutated file back from its pre-edit copy."""
    for path, copy in backups.items():
        shutil.copy2(copy, path)
        shutil.rmtree(copy.parent, ignore_errors=True)


def _run(mutation: Mutation) -> tuple[str, list[str]]:
    """Run the mutation's tests. Returns a verdict and the failing test names."""
    command = [
        "uv",
        "run",
        "pytest",
        *mutation.tests,
        "-q",
        "-p",
        "no:cacheprovider",
        "--no-cov",
        *mutation.extra_args,
    ]
    # Own process group, killed as a group in ``finally``.
    # ``subprocess.run(timeout=...)`` kills only its direct child, and only if
    # its own ``except`` gets to run. Kill a harness while a pytest is in
    # flight (Ctrl-C, an agent stopped, a terminal closed) and that pytest is
    # orphaned: three were once found alive two hours later, competing for the
    # same Postgres and Redis the rest of the suite uses, which is exactly the
    # load that makes unrelated tests flake.
    process = subprocess.Popen(
        command,
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=mutation.timeout)
    except subprocess.TimeoutExpired:
        if mutation.hang_is_failure:
            return "HUNG (the failure this prevents)", []
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


def main(mutations: Sequence[Mutation], *, description: str | None = None) -> int:
    """Run every mutation (or those matching ``-k``) and print a table.

    Args:
        mutations: The harness's table.
        description: ``--help`` text; a harness passes its ``__doc__``.

    Returns:
        A process exit code: non-zero if any chosen row was not falsified
        exactly as it declares.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-k", dest="pattern", default="", help="substring of the mutation name")
    parser.add_argument("--list", action="store_true", help="print the mutations and exit")
    parser.add_argument(
        "--check-anchors",
        action="store_true",
        help="apply every edit in memory and report stale or ambiguous anchors, without pytest",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="print each row's observed red set as an `expect=` tuple, for pasting back",
    )
    args = parser.parse_args()

    chosen = [m for m in mutations if args.pattern in m.name]
    width = max((len(m.name) for m in chosen), default=20) + 2
    if args.list:
        for mutation in chosen:
            print(f"{mutation.name:{width}} {mutation.breaks}")
        return 0
    if args.check_anchors:
        return check_anchors(chosen)

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
        print(f"{mutation.name:{width}} {verdict}", flush=True)
        if args.record:
            body = "".join(f'\n            "{name}",' for name in failures)
            print(f"        # {mutation.name}\n        expect=({body}\n        ),", flush=True)

    print("\n--- summary ---")
    # ``TIMED OUT`` belongs in this tuple: a mutation whose pytest hangs past
    # the timeout proves nothing, and counting it green would let a harness lie
    # about its own result — the thing ``_apply``'s SystemExit message says is
    # worse than having no harness at all.
    unfalsified = [
        name
        for name, verdict in rows
        if verdict.startswith(("UNFALSIFIED", "WRONG BLAST RADIUS", "TIMED OUT"))
    ]
    for name, verdict in rows:
        print(f"{name:{width}} {verdict}")
    if unfalsified:
        print(f"\n{len(unfalsified)} mutation(s) not falsified: {', '.join(unfalsified)}")
        return 1
    print(f"\nall {len(rows)} mutations falsified")
    return 0


__all__ = ["REPO", "SRC", "Mutation", "check_anchors", "main"]
