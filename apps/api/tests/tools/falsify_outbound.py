#!/usr/bin/env python
"""Mutation harness for the SSRF-safe outbound client.

Every safety property of :mod:`yupay.core.outbound` is only as good as the
test that fails when it is removed. This script breaks each one in turn and
checks that the tests it names actually go red — the difference between "the
suite passes" and "the suite would notice".

Run it::

    uv run python apps/api/tests/tools/falsify_outbound.py            # all
    uv run python apps/api/tests/tools/falsify_outbound.py -k redirect

It is committed because a falsification result nobody can re-run is a claim,
not evidence — and two rows of the first version's table turned out to be
wrong: one mutation was applied to a file the code had moved out of, and one
was masked by a second mitigation in front of it. Both were silent. So:

- every mutation asserts it **changed the file** before the suite runs, and
- a mutation whose suite stays green is reported as ``UNFALSIFIED``, loudly.

Sources are restored from a copy taken before the edit, in a ``finally``.
Never ``git checkout`` — several agents share this worktree.

Two mutations are expected to **hang** rather than fail (removing a timeout
means the client waits forever, which is the failure it prevents); those carry
their own short timeout and a hang counts as the expected failure.
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
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SRC = REPO / "apps/api/src/yupay"
UNIT = "apps/api/tests/unit/test_outbound_ssrf.py"
LIVE = "apps/api/tests/integration/test_outbound_ssrf_live.py"
IMAGE = "apps/api/tests/unit/test_catalog_image_url_safety.py"


@dataclass(frozen=True)
class Mutation:
    """One way to break the client, and the tests that must notice.

    Attributes:
        name: How the row is reported.
        breaks: What safety property this removes, for the report.
        edits: ``(path, old, new)`` triples. Each must change its file.
        tests: Test files (optionally ``file::name``) to run.
        expect: Test names that must be among the failures. Empty means "any
            failure will do".
        timeout: Seconds. A mutation that hangs is a mutation that removed a
            deadline, which counts as failing.
        hang_is_failure: Whether a timeout counts as the expected failure.
    """

    name: str
    breaks: str
    edits: tuple[tuple[Path, str, str], ...]
    tests: tuple[str, ...]
    expect: tuple[str, ...] = ()
    timeout: int = 900
    hang_is_failure: bool = False
    extra_args: Sequence[str] = field(default_factory=tuple)


#: ``FAILED apps/.../test_x.py::test_name[param] - AssertionError: …``. Split
#: on ``::`` and a parametrised IPv6 address (``[fec0::1]``) reports itself as
#: ``1]`` — which is how the first run of this harness said a mutation "failed,
#: but not on" a test it had in fact failed on.
_FAILED_LINE = re.compile(r"^FAILED\s+\S+?\.py::(?P<name>.+?)(?:\s+-\s.*)?$")

OUTBOUND = SRC / "core/outbound.py"
ADDRESSES = SRC / "core/outbound_addresses.py"
ERRORS = SRC / "core/outbound_errors.py"
TARGET = SRC / "core/outbound_target.py"
IMAGE_SAFETY = SRC / "modules/catalog/image_url_safety.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="policy_off",
        breaks="the address check refuses nothing",
        edits=(
            (
                OUTBOUND,
                "    if findings:\n        raise AddressNotAllowedError(",
                "    if False and findings:\n        raise AddressNotAllowedError(",
            ),
        ),
        tests=(UNIT, LIVE),
        expect=(
            "test_a_loopback_address_is_refused",
            "test_a_loopback_server_behind_a_public_looking_hostname_is_never_contacted",
        ),
    ),
    Mutation(
        name="site_local_missing",
        breaks="fec0::/10 falls through the family table and the catch-all",
        edits=(
            (
                ADDRESSES,
                '    ("site-local", lambda ip: isinstance(ip, ipaddress.IPv6Address)'
                " and ip.is_site_local),\n",
                "",
            ),
        ),
        tests=(UNIT, IMAGE),
        expect=("test_a_site_local_address_is_refused", "test_rejects_ipv6_site_local"),
    ),
    Mutation(
        name="guard_disarmed",
        breaks="the connect-time guard stops comparing the socket target",
        edits=(
            (OUTBOUND, "        if target != pinned:", "        if False and target != pinned:"),
        ),
        tests=(UNIT, LIVE),
        expect=(
            "test_the_guard_refuses_a_socket_target_that_is_not_the_pinned_address",
            "test_connecting_by_name_instead_of_the_pin_is_refused",
        ),
    ),
    Mutation(
        name="connect_by_name",
        breaks="the request is aimed at the hostname after the address was checked",
        edits=(
            (
                OUTBOUND,
                '    literal = f"[{address}]" if ":" in address else address',
                "    literal = target.host",
            ),
            (OUTBOUND, "        if target != pinned:", "        if False and target != pinned:"),
        ),
        tests=(LIVE,),
        expect=("test_the_connection_lands_on_the_address_the_policy_checked",),
    ),
    Mutation(
        name="follow_redirects",
        breaks="a 30x becomes a hop instead of an outcome",
        edits=(
            (
                OUTBOUND,
                "        follow_redirects=False,\n        trust_env=False,",
                "        follow_redirects=True,\n        trust_env=False,",
            ),
        ),
        tests=(UNIT,),
        expect=("test_a_redirect_is_returned_as_a_result_and_never_followed",),
    ),
    Mutation(
        name="size_cap_off",
        breaks="the response is read without a byte cap",
        edits=(
            (OUTBOUND, "        if total > max_bytes:", "        if False and total > max_bytes:"),
        ),
        tests=(
            f"{UNIT}::test_a_response_over_the_byte_cap_is_a_typed_refusal",
            f"{LIVE}::test_a_response_bigger_than_the_cap_is_refused",
        ),
        # Not the whole unit file on purpose: with no cap, the endless-stream
        # test reads until its deadline and eats memory doing it.
        expect=("test_a_response_over_the_byte_cap_is_a_typed_refusal",),
    ),
    Mutation(
        name="deadline_off",
        breaks="the total wall-clock budget stops applying",
        edits=((OUTBOUND, "        async with asyncio.timeout(timeout):", "        if True:"),),
        tests=(f"{UNIT}::test_a_body_that_drips_forever_hits_the_deadline",),
        timeout=25,
        hang_is_failure=True,
    ),
    Mutation(
        name="identity_off",
        breaks="the client stops asking for an undecoded body",
        edits=((OUTBOUND, '    out["accept-encoding"] = "identity"', "    pass"),),
        tests=(UNIT,),
        expect=("test_the_client_asks_for_an_undecoded_body",),
    ),
    Mutation(
        name="decoded_read",
        breaks="the body is read through httpx's decoder instead of off the wire",
        edits=(
            (
                OUTBOUND,
                "    async for chunk in response.aiter_raw():",
                "    async for chunk in response.aiter_bytes():",
            ),
        ),
        tests=(UNIT,),
        expect=("test_the_body_is_read_off_the_wire_and_never_through_the_decoder",),
    ),
    Mutation(
        name="encoding_refusal_off",
        breaks="a compressed answer is accepted and expanded in-process",
        edits=(
            (
                OUTBOUND,
                '    if encoding not in {"", "identity"}:',
                '    if False and encoding not in {"", "identity"}:',
            ),
            (
                OUTBOUND,
                "    async for chunk in response.aiter_raw():",
                "    async for chunk in response.aiter_bytes():",
            ),
        ),
        tests=(UNIT, LIVE),
        expect=("test_a_compressed_response_is_refused_and_never_expanded",),
    ),
    Mutation(
        name="idn_unencoded",
        breaks="the host is not IDNA-encoded before it is used",
        edits=(
            (
                TARGET,
                '    host = _ascii_host(hostname or "")',
                "    host = (hostname or '').rstrip('.')",
            ),
        ),
        tests=(UNIT,),
        expect=("test_an_idn_hostname_is_encoded_rather_than_refused",),
    ),
    Mutation(
        name="port_zero_coalesced",
        breaks="port 0 is read as 443",
        edits=(
            (
                TARGET,
                "    port = HTTPS_PORT if raw_port is None else raw_port\n    if port == 0:",
                "    port = raw_port or HTTPS_PORT\n    if False:",
            ),
        ),
        tests=(UNIT,),
        expect=("test_port_zero_is_refused_rather_than_read_as_443",),
    ),
    Mutation(
        name="untyped_resolution_error",
        breaks="a UnicodeError from getaddrinfo escapes untyped",
        edits=(
            (OUTBOUND, "    except (OSError, UnicodeError) as exc:", "    except OSError as exc:"),
        ),
        tests=(UNIT,),
        expect=("test_an_over_long_dns_label_is_a_typed_resolution_failure",),
    ),
    Mutation(
        name="catch_all_off",
        breaks="an unexpected exception escapes post_json untyped",
        edits=(
            (
                OUTBOUND,
                "    except Exception as exc:\n        # The net that makes",
                "    except ZeroDivisionError as exc:\n        # The net that makes",
            ),
        ),
        tests=(UNIT,),
        expect=("test_an_unexpected_failure_still_comes_out_typed",),
    ),
    Mutation(
        name="connect_timeout_after_generic_timeout",
        breaks="a handshake timeout is reported as UNKNOWN instead of NOT_SENT",
        edits=(
            (
                OUTBOUND,
                "        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:\n"
                "            # Nothing was written: the socket or the handshake never came up.",
                "        except httpx.TimeoutException as exc:\n"
                '            raise OutboundTimeoutError(f"{target.host} did not answer in time") from exc\n'
                "        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:\n"
                "            # Nothing was written: the socket or the handshake never came up.",
            ),
            (
                OUTBOUND,
                "            ) from exc\n"
                "        except httpx.TimeoutException as exc:\n"
                '            raise OutboundTimeoutError(f"{target.host} did not answer in time") from exc\n'
                "        except httpx.HTTPError as exc:",
                "            ) from exc\n        except httpx.HTTPError as exc:",
            ),
        ),
        tests=(UNIT,),
        expect=("test_a_handshake_timeout_is_a_connection_that_never_came_up",),
    ),
    Mutation(
        name="one_transport_failure",
        breaks="a broken exchange is reported as a connection that never came up",
        edits=(
            (
                OUTBOUND,
                "        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:",
                "        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPError) as exc:",
            ),
        ),
        tests=(UNIT,),
        expect=("test_a_broken_exchange_is_told_apart_from_a_connection_that_never_came_up",),
    ),
    Mutation(
        name="unclassified_leaf",
        breaks="an error is added in no family and decides no delivery",
        edits=(
            (
                ERRORS,
                "class OutboundUnreachableError(OutboundError):",
                'class WebhookRejectedError(OutboundError):\n    """Unclassified."""\n\n\n'
                "class OutboundUnreachableError(OutboundError):",
            ),
        ),
        tests=(UNIT,),
        expect=(
            "test_every_error_is_in_exactly_one_family",
            "test_every_error_decides_what_it_means_for_a_retry",
        ),
    ),
    Mutation(
        name="timeout_says_not_sent",
        breaks="a timeout claims nothing was delivered",
        edits=(
            (
                ERRORS,
                "    ``UNKNOWN``, not ``NOT_SENT``",
                "    ``NOT_SENT`` (mutation), not ``UNKNOWN``",
            ),
            (
                ERRORS,
                "    delivery: ClassVar[Delivery] = Delivery.UNKNOWN\n\n\n__all__",
                "    delivery: ClassVar[Delivery] = Delivery.NOT_SENT\n\n\n__all__",
            ),
        ),
        tests=(UNIT,),
        expect=("test_delivery_answers_what_a_retry_would_do", "test_a_timeout_is_not_reported"),
    ),
    Mutation(
        name="host_not_normalised",
        breaks="the image validator classifies a host Node would read differently",
        edits=(
            (
                IMAGE_SAFETY,
                '        host = normalize_host(parsed.hostname or "")',
                '        host = (parsed.hostname or "").lower().rstrip(".")',
            ),
        ),
        tests=(IMAGE,),
        expect=("test_rejects_the_spellings_node_resolves_to_loopback",),
    ),
    Mutation(
        name="ipv4_notation_unread",
        breaks="the image validator reads only ipaddress's spelling of an address",
        edits=(
            (
                IMAGE_SAFETY,
                "        return _whatwg_ipv4(host)",
                "        return None",
            ),
        ),
        tests=(IMAGE,),
        expect=("test_rejects_the_spellings_node_resolves_to_loopback",),
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
        mutated = source.replace(old, new)
        if mutated == source:
            message = (
                f"{mutation.name}: the edit changed nothing in {path.name}. "
                "A str.replace that matches nothing is a silent no-op, and a "
                "harness that reports GREEN from one is worse than no harness."
            )
            raise SystemExit(message)
        path.write_text(mutated)


def _restore(backups: dict[Path, Path]) -> None:
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
    #
    # Two mutations here hang on purpose, and ``subprocess.run(timeout=...)``
    # kills only its direct child — and only if its own ``except`` gets to run.
    # Kill this harness while a hung pytest is in flight (Ctrl-C, an agent
    # stopped, a terminal closed) and that pytest is orphaned. Three of them
    # were found alive after two hours on one occasion, competing for the same
    # Postgres and Redis the rest of the suite uses, which is exactly the kind
    # of load that makes unrelated tests flake.
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
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, "")
    failures = [
        match.group("name")
        for line in completed.stdout.splitlines()
        if (match := _FAILED_LINE.match(line))
    ]
    if completed.returncode == 0:
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
            print(f"{mutation.name:26} {mutation.breaks}")
        return 0

    rows: list[tuple[str, str, str]] = []
    for mutation in chosen:
        backups: dict[Path, Path] = {}
        try:
            _apply(mutation, backups)
            verdict, failures = _run(mutation)
        finally:
            _restore(backups)
        rows.append((mutation.name, verdict, ", ".join(failures[:3])))
        print(f"{mutation.name:26} {verdict}", flush=True)

    print("\n--- summary ---")
    unfalsified = [
        name for name, verdict, _ in rows if verdict.startswith(("UNFALSIFIED", "failed, but"))
    ]
    for name, verdict, shown in rows:
        print(f"{name:26} {verdict:44} {shown}")
    if unfalsified:
        print(f"\n{len(unfalsified)} mutation(s) not falsified: {', '.join(unfalsified)}")
        return 1
    print(f"\nall {len(rows)} mutations falsified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
