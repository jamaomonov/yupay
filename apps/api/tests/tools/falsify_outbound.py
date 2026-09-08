#!/usr/bin/env python
"""Mutation harness for the SSRF-safe outbound client.

Every safety property of :mod:`yupay.core.outbound` is only as good as the
test that fails when it is removed. This script breaks each one in turn and
checks that the tests it names actually go red — the difference between "the
suite passes" and "the suite would notice".

The runner, the guarantees it enforces and the rules for running one live in
:mod:`_falsify`; read that first. Run it::

    uv run python apps/api/tests/tools/falsify_outbound.py            # all
    uv run python apps/api/tests/tools/falsify_outbound.py -k redirect
    uv run python apps/api/tests/tools/falsify_outbound.py --check-anchors

It is committed because a falsification result nobody can re-run is a claim,
not evidence — and two rows of the first version's table turned out to be
wrong: one mutation was applied to a file the code had moved out of, and one
was masked by a second mitigation in front of it. Both were silent.

**Most rows run all three test files**, so the exact ``expect=`` set can see
collateral damage; 157 tests in about seven seconds. Two rows deliberately do
not, and say why at the row: ``size_cap_off`` (with no cap the endless-stream
test reads until its deadline and eats memory doing it) and ``deadline_off``.

``deadline_off`` is also the one row expected to **hang** rather than fail:
removing a deadline means the client waits forever, which is the failure the
deadline prevents. It carries a short ``timeout`` and ``hang_is_failure=True``.
"""

from __future__ import annotations

import sys

from _falsify import SRC, Mutation, main

UNIT = "apps/api/tests/unit/test_outbound_ssrf.py"
LIVE = "apps/api/tests/integration/test_outbound_ssrf_live.py"
IMAGE = "apps/api/tests/unit/test_catalog_image_url_safety.py"

OUTBOUND = SRC / "core/outbound.py"
ADDRESSES = SRC / "core/outbound_addresses.py"
ERRORS = SRC / "core/outbound_errors.py"
TARGET = SRC / "core/outbound_target.py"
IMAGE_SAFETY = SRC / "modules/catalog/image_url_safety.py"

#: The default for a row: all three files, so the blast radii below are
#: comparable with each other and an ``expect=`` set can see collateral damage.
#: 157 tests in about seven seconds. Two rows override it and say why.
TESTS = (UNIT, LIVE, IMAGE)


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        # Forty-seven tests, and that is the honest number: this row deletes
        # the address policy, and every address the policy refuses has a test.
        # A set this long is not a defect in the row — it is what "the check
        # refuses nothing" costs — but it does mean adding an address case to
        # the unit file changes this tuple. Re-record it rather than trimming
        # it; a trimmed set is a membership assertion wearing an equals sign.
        name="policy_off",
        breaks="the address check refuses nothing",
        edits=(
            (
                OUTBOUND,
                "    if findings:\n        raise AddressNotAllowedError(",
                "    if False and findings:\n        raise AddressNotAllowedError(",
            ),
        ),
        tests=TESTS,
        expect=(
            "test_a_carrier_grade_nat_address_is_refused[100.127.255.254]",
            "test_a_carrier_grade_nat_address_is_refused[100.64.0.1]",
            "test_a_link_local_address_is_refused[169.254.0.1]",
            "test_a_link_local_address_is_refused[169.254.169.254]",
            "test_a_link_local_address_is_refused[::ffff:169.254.169.254]",
            "test_a_link_local_address_is_refused[fe80::1]",
            "test_a_loopback_address_is_refused[127.0.0.1]",
            "test_a_loopback_address_is_refused[127.1.2.3]",
            "test_a_loopback_address_is_refused[::1]",
            "test_a_loopback_address_is_refused[::ffff:127.0.0.1]",
            "test_a_loopback_server_behind_a_public_looking_hostname_is_never_contacted",
            "test_a_multicast_address_is_refused[224.0.0.1]",
            "test_a_multicast_address_is_refused[239.255.255.250]",
            "test_a_multicast_address_is_refused[::ffff:224.0.0.1]",
            "test_a_multicast_address_is_refused[ff02::1]",
            "test_a_private_address_is_refused[10.0.0.1]",
            "test_a_private_address_is_refused[172.16.0.1]",
            "test_a_private_address_is_refused[172.31.255.254]",
            "test_a_private_address_is_refused[192.168.1.1]",
            "test_a_private_address_is_refused[::ffff:10.0.0.1]",
            "test_a_private_address_is_refused[::ffff:172.16.0.1]",
            "test_a_private_address_is_refused[::ffff:192.168.1.1]",
            "test_a_private_answer_listed_first_refuses_the_whole_host",
            "test_a_refusal_is_logged_without_the_body_either",
            "test_a_reserved_address_is_refused[240.0.0.1]",
            "test_a_reserved_address_is_refused[255.255.255.255]",
            "test_a_reserved_address_is_refused[64:ff9b::7f00:1]",
            "test_a_reserved_address_is_refused[::ffff:240.0.0.1]",
            "test_a_scoped_ipv6_answer_keeps_its_family",
            "test_a_site_local_address_is_refused[fec0::1]",
            "test_a_site_local_address_is_refused[feff:ffff:ffff:ffff::1]",
            "test_a_tunnelled_ipv6_address_is_refused[2001:0:4136:e378:8000:63bf:3fff:fdd2]",
            "test_a_tunnelled_ipv6_address_is_refused[2002:7f00:1::]",
            "test_a_unique_local_address_is_refused[fc00::1]",
            "test_a_unique_local_address_is_refused[fd12:3456:789a::1]",
            "test_an_answer_that_will_not_parse_is_refused[10.0.0.1 ]",
            "test_an_answer_that_will_not_parse_is_refused[300.1.2.3]",
            "test_an_answer_that_will_not_parse_is_refused[]",
            "test_an_answer_that_will_not_parse_is_refused[not-an-address]",
            "test_obfuscated_notation_is_resolved_rather_than_parsed[0x7f000001]",
            "test_obfuscated_notation_is_resolved_rather_than_parsed[127.1]",
            "test_obfuscated_notation_is_resolved_rather_than_parsed[2130706433]",
            "test_one_private_answer_beside_a_public_one_refuses_the_whole_host",
            "test_the_this_network_block_is_refused[0.0.0.0]",
            "test_the_this_network_block_is_refused[0.1.2.3]",
            "test_the_this_network_block_is_refused[::ffff:0.0.0.0]",
            "test_the_unspecified_ipv6_address_is_refused",
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
        tests=TESTS,
        expect=(
            "test_a_site_local_address_is_refused[fec0::1]",
            "test_a_site_local_address_is_refused[feff:ffff:ffff:ffff::1]",
            "test_rejects_ipv6_site_local",
            "test_rejects_ssrf_targets[https://[fec0::1]/x]",
        ),
    ),
    Mutation(
        name="guard_disarmed",
        breaks="the connect-time guard stops comparing the socket target",
        edits=(
            (OUTBOUND, "        if target != pinned:", "        if False and target != pinned:"),
        ),
        tests=TESTS,
        expect=(
            "test_connecting_by_name_instead_of_the_pin_is_refused",
            "test_the_guard_refuses_a_socket_target_that_is_not_the_pinned_address",
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
        tests=TESTS,
        expect=(
            "test_a_compressed_answer_is_refused_off_a_real_socket",
            "test_a_delivery_presents_the_hostname_and_returns_what_the_log_needs",
            "test_a_redirect_is_returned_as_a_result_and_never_followed",
            "test_a_redirect_to_the_metadata_address_is_an_outcome_not_a_hop",
            "test_a_response_bigger_than_the_cap_is_refused",
            "test_a_second_lookup_that_would_answer_differently_is_never_made",
            "test_a_server_that_never_answers_hits_the_deadline",
            "test_an_ipv6_answer_is_pinned_with_brackets",
            "test_an_ipv6_literal_in_the_url_keeps_its_brackets_in_the_host_header",
            "test_connecting_by_name_instead_of_the_pin_is_refused",
            "test_our_headers_go_to_the_pinned_host_and_nowhere_else",
            "test_the_connection_lands_on_the_address_the_policy_checked",
            "test_the_guard_refuses_a_socket_target_that_is_not_the_pinned_address",
            "test_the_request_goes_to_the_checked_address_not_the_hostname",
        ),
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
        tests=TESTS,
        expect=(
            "test_a_redirect_is_returned_as_a_result_and_never_followed",
            "test_a_redirect_to_the_metadata_address_is_an_outcome_not_a_hop",
            "test_every_redirect_status_is_an_outcome[301]",
            "test_every_redirect_status_is_an_outcome[302]",
            "test_every_redirect_status_is_an_outcome[303]",
            "test_every_redirect_status_is_an_outcome[307]",
            "test_every_redirect_status_is_an_outcome[308]",
            "test_our_headers_go_to_the_pinned_host_and_nowhere_else",
        ),
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
        expect=(
            "test_a_response_bigger_than_the_cap_is_refused",
            "test_a_response_over_the_byte_cap_is_a_typed_refusal",
        ),
    ),
    Mutation(
        # The one row with no ``expect``: the expected outcome is the hang, and
        # a hang has no red set. If this ever reports WRONG BLAST RADIUS the
        # mutation stopped hanging, which is itself the finding.
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
        tests=TESTS,
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
        tests=TESTS,
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
        tests=TESTS,
        expect=(
            "test_a_compressed_answer_is_refused_off_a_real_socket",
            "test_a_compressed_response_is_refused_and_never_expanded",
            "test_the_body_is_read_off_the_wire_and_never_through_the_decoder",
        ),
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
        tests=TESTS,
        expect=(
            "test_a_host_that_will_not_encode_is_a_typed_refusal",
            "test_a_url_without_a_host_is_refused",
            "test_an_idn_hostname_is_encoded_rather_than_refused",
        ),
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
        tests=TESTS,
        expect=("test_port_zero_is_refused_rather_than_read_as_443",),
    ),
    Mutation(
        name="untyped_resolution_error",
        breaks="a UnicodeError from getaddrinfo escapes untyped",
        edits=(
            (OUTBOUND, "    except (OSError, UnicodeError) as exc:", "    except OSError as exc:"),
        ),
        tests=TESTS,
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
        tests=TESTS,
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
        tests=TESTS,
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
        tests=TESTS,
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
        tests=TESTS,
        expect=(
            "test_every_error_decides_what_it_means_for_a_retry",
            "test_every_error_is_in_exactly_one_family",
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
        tests=TESTS,
        expect=(
            "test_a_timeout_is_not_reported_as_nothing_sent",
            "test_delivery_answers_what_a_retry_would_do[OutboundTimeoutError-unknown]",
        ),
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
        tests=TESTS,
        expect=(
            "test_rejects_the_spellings_node_resolves_to_loopback[https://127\\u30020\\u30020\\u30021/x.png]",
            "test_rejects_the_spellings_node_resolves_to_loopback[https://\\u24db\\u24de\\u24d2\\u24d0\\u24db\\u24d7\\u24de\\u24e2\\u24e3/x.png]",
            "test_rejects_the_spellings_node_resolves_to_loopback[https://\\uff11\\uff12\\uff17.\\uff10.\\uff10.\\uff11/x.png]",
        ),
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
        tests=TESTS,
        expect=(
            "test_rejects_ssrf_targets[https://2130706433/x]",
            "test_rejects_the_spellings_node_resolves_to_loopback[https://0/x.png]",
            "test_rejects_the_spellings_node_resolves_to_loopback[https://0177.0.0.1/x.png]",
            "test_rejects_the_spellings_node_resolves_to_loopback[https://0x7f.1/x.png]",
            "test_rejects_the_spellings_node_resolves_to_loopback[https://127.1/x.png]",
            "test_rejects_the_spellings_node_resolves_to_loopback[https://2130706433/x.png]",
        ),
    ),
)


if __name__ == "__main__":
    sys.exit(main(MUTATIONS, description=__doc__))
