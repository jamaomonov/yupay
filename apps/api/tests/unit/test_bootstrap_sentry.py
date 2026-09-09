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
