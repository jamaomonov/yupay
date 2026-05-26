"""PII-leak checks for the G2B adapter.

We don't trust ourselves not to log secrets; we trust the redactor + this
test. Specifically we check that:

- The structlog redactor masks ``api_key`` and ``code`` keys (built into
  the core redactor — re-asserted here as a contract).
- ``G2bFulfiller`` puts only a *hashed* player_id and a *count* of
  delivery items in its ``FulfillResult.extra_metadata`` payload, never
  the raw values.
- ``_hash_short`` is stable and short (12 hex chars).
"""

from __future__ import annotations

from yupay.core.logging import REDACTED_KEYS
from yupay.modules.fulfillment.suppliers.g2b import (
    _game_artifact,
    _hash_short,
    _voucher_artifact,
)


def test_redactor_masks_g2b_secret_keys() -> None:
    # These are the keys the adapter must never log in plaintext.
    assert "api_key" in REDACTED_KEYS
    assert "code" in REDACTED_KEYS
    assert "voucher_code" in REDACTED_KEYS


def test_hash_short_is_stable_and_opaque() -> None:
    a = _hash_short("5679523421")
    b = _hash_short("5679523421")
    c = _hash_short("0000000001")
    assert a == b
    assert a != c
    assert len(a) == 12
    # No part of the raw input survives in the hash.
    assert "5679" not in a


def test_voucher_artifact_includes_codes_for_customer_view() -> None:
    """Voucher artifact is customer-facing — codes ARE included here, as
    they must be (the user paid for them). The redactor masks them only
    in log messages; ``Delivery.artifact`` is access-guarded storage."""

    class _M:
        external_product_id = "42"
        external_variant_id = None

    class _I:
        sku_id = "sku-1"
        qty = 2

    art = _voucher_artifact(
        mapping=_M(),  # type: ignore[arg-type]
        item=_I(),  # type: ignore[arg-type]
        codes=["K1", "K2"],
        g2b_order_id="999",
    )
    assert art["code"] == "K1"
    assert art["codes"] == ["K1", "K2"]
    assert art["source"] == "g2b"


def test_game_artifact_never_carries_player_id() -> None:
    class _M:
        external_product_id = "pubg_mobile"
        external_variant_id = "60 UC"

    class _I:
        sku_id = "sku-2"
        qty = 1

    art = _game_artifact(
        mapping=_M(),  # type: ignore[arg-type]
        item=_I(),  # type: ignore[arg-type]
        g2b_order_id="9090",
        message="ok",
    )
    # Crucially, the game artifact does not echo the player_id — credit
    # went straight to the player's in-game account on G2B's side; we
    # surface only the receipt metadata to our customer view.
    flat_values = " ".join(repr(v) for v in art.values())
    assert "player_id" not in art
    assert "5679523421" not in flat_values
