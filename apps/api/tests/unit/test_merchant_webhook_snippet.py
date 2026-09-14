"""The verification snippet in the docs must actually verify.

Spec §10 asks the docs to carry one, and a snippet that does not work is worse
than none: an integrator who pastes it and sees deliveries rejected will reach
for the shortcut that makes the rejections stop, which is to stop verifying.

So this does not *mirror* the snippet — it **reads it out of the document** and
runs it against real signatures from ``merchants.signing``. Nothing can drift:
edit either side and this fails.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from yupay.modules.merchants import signing

_README = Path(__file__).resolve().parents[2] / "src/yupay/modules/merchants/README.md"
_SECTION = "### Verifying a delivery"
_SECRET = "ypmw_test_secret_value"


def _snippet_verify() -> Callable[[dict[str, str], bytes], bool]:
    """Execute the README's Python block and hand back its ``verify``."""
    text = _README.read_text(encoding="utf-8")
    start = text.index(_SECTION)
    block = re.search(r"```python\n(.*?)```", text[start:], re.DOTALL)
    assert block is not None, f"no python block under {_SECTION!r}"
    namespace: dict[str, Any] = {}
    exec(compile(block.group(1), str(_README), "exec"), namespace)
    namespace["SECRET"] = _SECRET
    verify = namespace["verify"]
    assert callable(verify)
    return verify  # type: ignore[no-any-return]


def _signed(body: bytes, *, timestamp: str) -> dict[str, str]:
    """Headers as ``webhook_delivery`` actually sends them."""
    message = signing.webhook_canonical_message(
        timestamp=timestamp,
        delivery_id="01a0aaaa-bbbb-7ccc-8ddd-eeeeffff0000",
        event_type="order.status_changed",
        body=body,
    )
    return {
        "X-Yupay-Timestamp": timestamp,
        "X-Yupay-Delivery": "01a0aaaa-bbbb-7ccc-8ddd-eeeeffff0000",
        "X-Yupay-Event": "order.status_changed",
        "X-Yupay-Signature": signing.expected_signature(_SECRET, message),
    }


@pytest.fixture
def verify() -> Callable[[dict[str, str], bytes], bool]:
    return _snippet_verify()


def test_the_documented_snippet_accepts_what_we_actually_send(
    verify: Callable[[dict[str, str], bytes], bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b'{"event":"order.status_changed","order_id":"01a0"}'
    monkeypatch.setattr("time.time", lambda: 1_757_000_000.0)

    assert verify(_signed(body, timestamp="1757000000"), body) is True


def test_a_tampered_body_is_rejected(
    verify: Callable[[dict[str, str], bytes], bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason the digest is over the raw bytes and not a parsed object."""
    body = b'{"event":"order.status_changed","order_id":"01a0"}'
    headers = _signed(body, timestamp="1757000000")
    monkeypatch.setattr("time.time", lambda: 1_757_000_000.0)

    assert verify(headers, body.replace(b"01a0", b"01a1")) is False


@pytest.mark.parametrize(
    "header",
    ["X-Yupay-Delivery", "X-Yupay-Event", "X-Yupay-Timestamp"],
)
def test_every_signed_field_is_actually_checked(
    verify: Callable[[dict[str, str], bytes], bool],
    monkeypatch: pytest.MonkeyPatch,
    header: str,
) -> None:
    """All four fields are in the canonical string, so all four must bind.

    The delivery id especially: it is in there so a replay can be recognised,
    and a snippet that ignored it would leave the receiver with a header it has
    no reason to trust.
    """
    body = b'{"event":"order.status_changed"}'
    headers = _signed(body, timestamp="1757000000")
    headers[header] = "1757000001" if header == "X-Yupay-Timestamp" else "tampered"
    monkeypatch.setattr("time.time", lambda: 1_757_000_000.0)

    assert verify(headers, body) is False


def test_a_stale_delivery_is_rejected(
    verify: Callable[[dict[str, str], bytes], bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correct signature is not enough on its own — it stays correct forever."""
    body = b'{"event":"order.status_changed"}'
    headers = _signed(body, timestamp="1757000000")
    monkeypatch.setattr("time.time", lambda: 1_757_000_000.0 + 301)

    assert verify(headers, body) is False
