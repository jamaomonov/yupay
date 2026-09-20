"""``init_sentry`` must silence *both* of Sentry's privacy switches.

`send_default_pii` governs request bodies, headers, cookies and user
identity. `include_local_variables` governs the stack-frame locals attached
to every exception event, and it defaults to ``True``. Setting only the first
looks like the intent was handled and is not: any 500 raised while a secret
is a live local — a freshly minted merchant API key or webhook signing
secret, each of which exists in the clear in exactly one frame — ships that
secret to a third-party SaaS.

This pins the call arguments, which is the falsifiable half. The end-to-end
half was done on prod on 2026-09-09 (event 80e82e4423c347828473bf82fe00352c,
no ``vars`` key on the frame); see docs/runbooks/first-deploy.md.
"""

from __future__ import annotations

from typing import Any

import pytest
from yupay.core.config import Settings
from yupay.core.observability import init_sentry


@pytest.fixture
def captured_init(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``sentry_sdk.init`` and hand back the kwargs it was called with."""
    import sentry_sdk

    seen: dict[str, Any] = {}

    def _fake_init(**kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", _fake_init)
    return seen


def test_both_privacy_switches_are_off(captured_init: dict[str, Any]) -> None:
    settings = Settings(sentry_dsn="https://public@example.invalid/1")

    init_sentry(settings)

    assert captured_init["send_default_pii"] is False
    # The one that defaults to True. Deleting this line is how the exposure
    # came back the first time.
    assert captured_init["include_local_variables"] is False


def test_no_dsn_initialises_nothing(captured_init: dict[str, Any]) -> None:
    """No DSN, no SDK — the dev default, and the reason the import is inline."""
    init_sentry(Settings(sentry_dsn=""))

    assert captured_init == {}


def test_every_service_that_can_crash_reports(captured_init: dict[str, Any]) -> None:
    """The API is not the only process that can raise.

    `init_sentry` lived in `bootstrap.py` until 2026-09-09, so only the API
    ever called it — while the worker, the scheduler and the bot loaded the
    same `api.env`, held the DSN, and reported nothing. The drain, the refund
    seam and the webhook delivery all run in the worker, which is the half of
    the system where an unreported crash costs money.

    This walks the three entrypoints for the call rather than trusting a
    comment, because the failure is silent: a service that never initialises
    Sentry looks exactly like one that has had no errors.
    """
    import ast
    import pathlib

    roots = {
        "worker": "apps/worker/src/yupay_worker/consumer.py",
        "scheduler": "apps/scheduler/src/yupay_scheduler/main.py",
        "bot": "apps/bot/src/yupay_bot/main.py",
    }
    repo = pathlib.Path(__file__).resolve().parents[4]
    missing = []
    for service, rel in roots.items():
        tree = ast.parse((repo / rel).read_text(encoding="utf-8"))
        called = any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "init_sentry")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "init_sentry")
            )
            for node in ast.walk(tree)
        )
        if not called:
            missing.append(f"{service} ({rel})")

    assert not missing, (
        "these services can crash and would report nothing: "
        + ", ".join(missing)
        + ". They load the same api.env as the API and hold the DSN; what they "
        "lack is the call."
    )


# ---------- the third leak: a bot token inside a breadcrumb URL ----------
#
# Neither switch above touches a breadcrumb. aiogram talks to
# `https://api.telegram.org/bot<token>/<method>`, the SDK records every
# outgoing request as a breadcrumb WITH its URL, and so every event the bot
# reported carried full control of the bot in plain text. Found 2026-09-21 in
# a real event, legible beside the stack trace.

_URL = "https://api.telegram.org/bot8702808191:AAHZi3f7JL2te_qYhQUoWt_s8O1WzrAPFiE/sendMessage"


def _hooks(captured: dict[str, Any]) -> tuple[Any, Any]:
    init_sentry(Settings(sentry_dsn="https://public@example.invalid/1"))
    return captured["before_breadcrumb"], captured["before_send"]


def test_a_token_in_a_breadcrumb_url_is_redacted(captured_init: dict[str, Any]) -> None:
    before_breadcrumb, _ = _hooks(captured_init)

    out = before_breadcrumb({"type": "http", "data": {"url": _URL}}, {})

    assert "AAHZi3f7JL2te" not in str(out)
    # The numeric bot id survives: it is public, and without it the breadcrumb
    # stops answering "which bot was this?".
    assert out["data"]["url"] == ("https://api.telegram.org/bot8702808191:[redacted]/sendMessage")


def test_a_token_in_a_breadcrumb_message_is_redacted(captured_init: dict[str, Any]) -> None:
    """The stdlib-logging integration puts the same text in ``message``.

    A scrubber that knew only ``data["url"]`` would have left this one
    shipping the token — which is why the walk is deep.
    """
    before_breadcrumb, _ = _hooks(captured_init)

    out = before_breadcrumb({"category": "httplib", "message": f"GET {_URL}"}, {})

    assert "AAHZi3f7JL2te" not in str(out)


def test_a_token_in_an_exception_value_is_redacted(captured_init: dict[str, Any]) -> None:
    _, before_send = _hooks(captured_init)

    event = {
        "exception": {"values": [{"type": "ClientError", "value": f"POST {_URL} failed"}]},
        "request": {"url": _URL},
    }
    out = before_send(event, {})

    assert "AAHZi3f7JL2te" not in str(out)
    assert out["exception"]["values"][0]["type"] == "ClientError"


def test_ordinary_text_is_left_alone(captured_init: dict[str, Any]) -> None:
    """The pattern is anchored on ``/bot<digits>:`` so it cannot fire on prose.

    Over-scrubbing an error message is its own bug: it makes an incident
    harder to read in exchange for nothing.
    """
    before_breadcrumb, _ = _hooks(captured_init)

    crumb = {"message": "robot: connection reset by peer /bot/help", "data": {"n": 7}}
    assert before_breadcrumb(dict(crumb), {}) == crumb
