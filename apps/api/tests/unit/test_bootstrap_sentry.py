"""``_init_sentry`` must silence *both* of Sentry's privacy switches.

`send_default_pii` governs request bodies, headers, cookies and user
identity. `include_local_variables` governs the stack-frame locals attached
to every exception event, and it defaults to ``True``. Setting only the first
looks like the intent was handled and is not: any 500 raised while a secret
is a live local — a freshly minted merchant API key or webhook signing
secret, each of which exists in the clear in exactly one frame — ships that
secret to a third-party SaaS.

This pins the call arguments, which is the falsifiable half. Proving nothing
reaches Sentry end to end needs a live DSN and is not done here.
"""

from __future__ import annotations

from typing import Any

import pytest
from yupay.bootstrap import _init_sentry
from yupay.core.config import Settings


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

    _init_sentry(settings)

    assert captured_init["send_default_pii"] is False
    # The one that defaults to True. Deleting this line is how the exposure
    # came back the first time.
    assert captured_init["include_local_variables"] is False


def test_no_dsn_initialises_nothing(captured_init: dict[str, Any]) -> None:
    """No DSN, no SDK — the dev default, and the reason the import is inline."""
    _init_sentry(Settings(sentry_dsn=""))

    assert captured_init == {}
