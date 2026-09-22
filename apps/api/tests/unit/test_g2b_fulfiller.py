"""G2bFulfiller branches with a fake client: guards, low-balance heuristics,
voucher/game purchase outcomes, status reconciliation, health probe.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from yupay.core import config as cfg
from yupay.modules.fulfillment.suppliers.base import FulfillerError
from yupay.modules.fulfillment.suppliers.g2b import (
    LOW_BALANCE_ERROR,
    G2bFulfiller,
    _is_an_unbilled_player_rejection,
    _looks_like_low_balance,
    _stringify_or_none,
)
from yupay.modules.fulfillment.suppliers.g2b_client import (
    G2bClient,
    G2bError,
    G2bTerminalFailure,
    GameOrderCreated,
    GameOrderStatus,
    VoucherDeliveryResult,
    VoucherPurchaseResult,
)


@pytest.fixture
def _g2b_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_CALLBACK_URL", "")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


class _FakeClient(G2bClient):
    """G2bClient with every network call replaced by canned behaviour."""

    def __init__(self, **canned: Any) -> None:
        super().__init__(api_key="test-key", base_url="https://g2b.test")
        self._canned = canned
        self.game_order_kwargs: dict[str, Any] = {}

    def _resolve(self, name: str) -> Any:
        value = self._canned[name]
        if isinstance(value, Exception):
            raise value
        return value

    async def get_me(self) -> dict[str, Any]:  # type: ignore[override]
        return cast(dict[str, Any], self._resolve("get_me"))

    async def purchase_voucher(self, **_kw: Any) -> VoucherPurchaseResult:  # type: ignore[override]
        return cast(VoucherPurchaseResult, self._resolve("purchase_voucher"))

    async def poll_voucher_delivery(self, *_a: Any, **_kw: Any) -> VoucherDeliveryResult:  # type: ignore[override]
        return cast(VoucherDeliveryResult, self._resolve("poll_voucher_delivery"))

    async def create_game_order(self, **kw: Any) -> GameOrderCreated:  # type: ignore[override]
        self.game_order_kwargs = kw
        return cast(GameOrderCreated, self._resolve("create_game_order"))

    async def get_game_order_status(self, **_kw: Any) -> GameOrderStatus:  # type: ignore[override]
        return cast(GameOrderStatus, self._resolve("get_game_order_status"))


def _mapping(kind: str = "voucher", variant: str | None = "VAR-1") -> Any:
    return SimpleNamespace(
        kind=kind, external_product_id="EP-1", external_variant_id=variant, quantity=1
    )


def _item(**fulfillment_data: Any) -> Any:
    return SimpleNamespace(
        id="item-123456789abc",
        sku_id="sku-1",
        qty=1,
        fulfillment_data=fulfillment_data,
        sku=None,  # no cost data → the balance pre-flight is skipped
    )


def _fulfiller(client: _FakeClient, mapping: Any) -> G2bFulfiller:
    gw = G2bFulfiller(client=client)

    async def _fake_load_mapping(db: Any, sku_id: str) -> Any:
        return mapping

    gw._load_mapping = _fake_load_mapping  # type: ignore[method-assign]
    return gw


class _FakeDB:
    """Just enough AsyncSession for check_status's OrderItem lookup."""

    def __init__(self, item: Any) -> None:
        self._item = item

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalar_one=lambda: self._item)


# ---------- guards & helpers ----------


async def test_guards_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("G2B_API_KEY", "")
    cfg.get_settings.cache_clear()
    try:
        gw = G2bFulfiller()
        with pytest.raises(FulfillerError, match="not configured"):
            await gw.fulfill(
                db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="k"
            )
        with pytest.raises(FulfillerError, match="not configured"):
            await gw.check_status(db=cast(Any, None), task=cast(Any, None))
    finally:
        cfg.get_settings.cache_clear()


async def test_check_status_requires_external_order_id(_g2b_env: None) -> None:
    gw = G2bFulfiller(client=_FakeClient())
    task = cast(Any, SimpleNamespace(external_order_id=None))
    with pytest.raises(FulfillerError, match="no G2B order id"):
        await gw.check_status(db=cast(Any, None), task=task)


def test_low_balance_heuristic() -> None:
    assert _looks_like_low_balance(G2bError(402, "Insufficient funds")) is True
    assert _looks_like_low_balance(G2bError(400, "Not enough balance")) is True
    assert _looks_like_low_balance(G2bError(400, "malformed payload")) is False
    assert _looks_like_low_balance(G2bError(500, "insufficient funds")) is False


#: The exact body G2B answered a real game create with on 2026-09-09
#: (merchant order ``m3b-parkA-1``, HTTP 400). Every match below is measured
#: against this string, not against a paraphrase of it.
LIVE_INVALID_PLAYER_BODY = (
    '{"message":"Invalid player ID. Please check and try again.","success":false}'
)


def test_the_live_invalid_player_body_is_recognised() -> None:
    """The exact production response of 2026-09-09, and nothing paraphrased."""
    assert _is_an_unbilled_player_rejection(G2bError(400, LIVE_INVALID_PLAYER_BODY)) is True


@pytest.mark.parametrize(
    "body",
    [
        # Their envelope, a different refusal — not the one the owner ruled on.
        pytest.param(
            '{"message":"Catalogue item not found.","success":false}',
            id="another-message",
        ),
        # Their envelope, but not a refusal at all. **The message is the
        # observed one verbatim**, so this row differs from the accepted body
        # in `success` and in nothing else — otherwise the flag is not what
        # the test is grading, which is how the harness found it vacuous.
        pytest.param(
            '{"message":"Invalid player ID. Please check and try again.","success":true}',
            id="not-a-refusal",
        ),
        # The exact message outside their envelope — an HTML error page, a
        # proxy, anything that is not G2B answering us in JSON. Same
        # discipline: only the envelope differs.
        pytest.param("Invalid player ID. Please check and try again.", id="not-their-envelope"),
        # Valid JSON, but not an object: nothing to read a refusal off.
        pytest.param('"Invalid player ID. Please check and try again."', id="json-not-an-object"),
        # Their envelope with a message that is not text at all.
        pytest.param('{"message":7,"success":false}', id="message-not-a-string"),
        # The phrase buried mid-message is a different message. We do not
        # extrapolate from a rejection we have not seen.
        pytest.param(
            '{"message":"Order failed: invalid player id","success":false}',
            id="phrase-buried-mid-message",
        ),
        # A message that merely *starts* the same way is not the same
        # message.
        pytest.param(
            '{"message":"Invalid player identifier for this game.","success":false}',
            id="longer-word-at-the-anchor",
        ),
        # **The expensive one.** A rejection that opens with the words we know
        # and then says something we have never been told about. An earlier
        # version of this matcher anchored at the start and returned True
        # here, which would have refunded a refusal G2B billed us for.
        pytest.param(
            '{"message":"Invalid player ID; the order was created and charged","success":false}',
            id="reworded-suffix",
        ),
        # Its mirror: the words we know, prefixed. Also a message we have
        # never seen, so also a park.
        pytest.param(
            '{"message":"Rejected. Invalid player ID. Please check and try again.",'
            '"success":false}',
            id="prefix-before-the-phrase",
        ),
        # And the shortened variant. Equality is deliberately brittle: G2B
        # rewording this at all sends the order back to the manual lane it
        # was in before M3c, which is the cheap direction to fail in.
        pytest.param(
            '{"message":"Invalid player ID.","success":false}',
            id="shortened-variant",
        ),
    ],
)
def test_only_g2bs_own_invalid_player_shape_is_recognised(body: str) -> None:
    """The tight twin of ``test_low_balance_heuristic``, and tight on purpose.

    A false positive there costs an admin one glance at the wrong queue. A
    false positive here posts a merchant refund for goods we may have paid
    for, so every body below is one we would rather park than guess about.
    """
    assert _is_an_unbilled_player_rejection(G2bError(400, body)) is False


def test_the_right_words_at_the_wrong_status_are_not_recognised() -> None:
    """A 5xx says nothing about our balance, whatever the body carries."""
    assert _is_an_unbilled_player_rejection(G2bError(500, LIVE_INVALID_PLAYER_BODY)) is False


def test_stringify_or_none() -> None:
    assert _stringify_or_none(None) is None
    assert _stringify_or_none("   ") is None
    assert _stringify_or_none(42) == "42"


async def test_cancel_is_a_noop(_g2b_env: None) -> None:
    gw = G2bFulfiller(client=_FakeClient())
    await gw.cancel(db=cast(Any, None), task=cast(Any, None))  # not raising IS the contract


# ---------- health ----------


async def test_health_states(_g2b_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    ok = G2bFulfiller(client=_FakeClient(get_me={"balance": "12.5", "username": "yupay"}))
    assert await ok.health() == {"available": True, "balance": "12.5", "username": "yupay"}

    http_err = G2bFulfiller(client=_FakeClient(get_me=G2bError(503, "down")))
    assert (await http_err.health())["reason"] == "g2b HTTP 503"

    weird = G2bFulfiller(client=_FakeClient(get_me=RuntimeError("dns exploded")))
    assert "dns exploded" in (await weird.health())["reason"]

    monkeypatch.setenv("G2B_API_KEY", "")
    cfg.get_settings.cache_clear()
    assert (await G2bFulfiller().health())["available"] is False


# ---------- voucher purchases ----------


async def test_voucher_purchase_outcomes(_g2b_env: None) -> None:
    mapping = _mapping("voucher")

    completed = _fulfiller(
        _FakeClient(
            purchase_voucher=VoucherPurchaseResult(
                g2b_order_id="g1", status="completed", delivery_items=["AAA", "BBB"]
            )
        ),
        mapping,
    )
    out = await completed.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="k1"
    )
    assert out.outcome == "succeeded"
    assert out.artifact is not None
    assert out.artifact["codes"] == ["AAA", "BBB"]

    pending = _fulfiller(
        _FakeClient(
            purchase_voucher=VoucherPurchaseResult(
                g2b_order_id="g2", status="pending", delivery_items=None
            )
        ),
        mapping,
    )
    out = await pending.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="k2"
    )
    assert out.outcome == "in_progress"
    assert out.external_order_id == "g2"

    failed = _fulfiller(
        _FakeClient(
            purchase_voucher=VoucherPurchaseResult(
                g2b_order_id="g3", status="failed", delivery_items=None
            )
        ),
        mapping,
    )
    out = await failed.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="k3"
    )
    assert out.outcome == "failed"


async def test_voucher_completed_without_codes_is_not_delivered(_g2b_env: None) -> None:
    """A ``completed`` status carrying zero codes must NOT mark the order delivered.

    G2B occasionally returns ``completed`` before the codes are attached (or with
    an empty list on a supplier glitch). Marking that ``succeeded`` would deliver
    an empty voucher artifact (``code=""``) to a customer who paid — the order
    then looks fulfilled and no refund/retry ever fires. Route it to
    ``in_progress`` so the poller keeps trying and ops can see it, never
    ``succeeded``.
    """
    mapping = _mapping("voucher")
    empties: list[list[str] | None] = [[], None]
    for empty in empties:
        gw = _fulfiller(
            _FakeClient(
                purchase_voucher=VoucherPurchaseResult(
                    g2b_order_id="ge", status="completed", delivery_items=empty
                )
            ),
            mapping,
        )
        out = await gw.fulfill(
            db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ke"
        )
        assert out.outcome == "in_progress"
        assert out.artifact is None


async def test_check_status_completed_without_codes_is_not_delivered(_g2b_env: None) -> None:
    """Same empty-codes guard on the poll path: completed-but-empty stays in_progress."""
    mapping = _mapping("voucher")
    task = cast(Any, SimpleNamespace(external_order_id="g1", order_item_id="oi1"))
    db = cast(Any, _FakeDB(_item()))
    empties: list[list[str] | None] = [[], None]
    for empty in empties:
        gw = _fulfiller(
            _FakeClient(
                poll_voucher_delivery=VoucherDeliveryResult(
                    status="completed", delivery_items=empty
                )
            ),
            mapping,
        )
        status = await gw.check_status(db=db, task=task)
        assert status.outcome == "in_progress"
        assert status.artifact is None


async def test_voucher_purchase_error_mapping(_g2b_env: None) -> None:
    mapping = _mapping("voucher")

    low = _fulfiller(_FakeClient(purchase_voucher=G2bError(402, "insufficient funds")), mapping)
    out = await low.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="k4"
    )
    assert out.error == LOW_BALANCE_ERROR
    assert out.extra_metadata["low_balance"] is True

    hard = _fulfiller(_FakeClient(purchase_voucher=G2bError(409, "conflict")), mapping)
    with pytest.raises(FulfillerError, match="HTTP 409"):
        await hard.fulfill(
            db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="k5"
        )


# ---------- game orders ----------


async def test_game_order_requires_player_and_variant(_g2b_env: None) -> None:
    gw = _fulfiller(_FakeClient(), _mapping("game"))
    with pytest.raises(FulfillerError, match="no player identifier"):
        await gw.fulfill(
            db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="k"
        )

    gw = _fulfiller(_FakeClient(), _mapping("game", variant=None))
    with pytest.raises(FulfillerError, match="external_variant_id"):
        await gw.fulfill(
            db=cast(Any, None),
            order=cast(Any, None),
            item=_item(player_id="p-1"),
            idempotency_key="k",
        )


async def test_a_telegram_username_is_a_player_identifier_too(_g2b_env: None) -> None:
    """The failover bug, in one call.

    Nineteen of the twenty G2B-mapped products key the identifier
    ``player_id``; Telegram Premium keys it ``username``, because what credits
    a Telegram account is an @handle. Reading only ``player_id`` refused that
    one product — and refused it exactly where it mattered: on 2026-09-22 NOVA
    declined a Premium order, fulfilment fell over to G2B as designed, and G2B
    turned down a line it could have filled. It was bought by hand instead.
    """
    client = _FakeClient(create_game_order=GameOrderCreated(g2b_order_id="go1", status="completed"))
    gw = _fulfiller(client, _mapping("game"))

    await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(username="@durov"),
        idempotency_key="k",
    )

    # The wire key stays ``player_id`` for every game — G2B's own
    # ``/games/fields`` calls it ``userid`` everywhere, Telegram included, and
    # that is their word for the concept, not the request field.
    assert client.game_order_kwargs.get("player_id") == "@durov"


async def test_player_id_still_wins_when_a_form_carries_both(_g2b_env: None) -> None:
    """Order matters, and it is not alphabetical: every line that works today
    carries ``player_id``, so it keeps priority and nothing existing can change
    behaviour because a second key appeared beside it."""
    client = _FakeClient(create_game_order=GameOrderCreated(g2b_order_id="go1", status="completed"))
    gw = _fulfiller(client, _mapping("game"))

    await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(player_id="719918738", username="@someone"),
        idempotency_key="k",
    )

    assert client.game_order_kwargs.get("player_id") == "719918738"


async def test_game_order_passes_the_server_field_to_g2b(_g2b_env: None) -> None:
    """The product's server field is keyed ``server`` (e.g. Genshin: os_euro),
    which is what the order stores in ``fulfillment_data``. The adapter must send
    that as G2B's ``server_id`` — reading the wrong key drops the server and G2B
    rejects the game order with HTTP 400 (prod incident 2026-08-05)."""
    client = _FakeClient(create_game_order=GameOrderCreated(g2b_order_id="go1", status="completed"))
    gw = _fulfiller(client, _mapping("game"))
    await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(player_id="719918738", server="os_euro"),
        idempotency_key="k",
    )
    assert client.game_order_kwargs.get("server_id") == "os_euro"


async def test_game_order_outcomes(_g2b_env: None) -> None:
    mapping = _mapping("game")
    item = _item(player_id="p-1", server="eu", charname="hero")

    done = _fulfiller(
        _FakeClient(create_game_order=GameOrderCreated(g2b_order_id="go1", status="completed")),
        mapping,
    )
    out = await done.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=item, idempotency_key="k1"
    )
    assert out.outcome == "succeeded"
    assert out.artifact is not None
    assert out.artifact["external_order_id"] == "go1"

    failed = _fulfiller(
        _FakeClient(create_game_order=GameOrderCreated(g2b_order_id="go2", status="failed")),
        mapping,
    )
    out = await failed.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=item, idempotency_key="k2"
    )
    assert out.outcome == "failed"

    low = _fulfiller(_FakeClient(create_game_order=G2bError(403, "balance too low")), mapping)
    out = await low.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=item, idempotency_key="k3"
    )
    assert out.error == LOW_BALANCE_ERROR

    hard = _fulfiller(_FakeClient(create_game_order=G2bError(410, "gone")), mapping)
    with pytest.raises(FulfillerError, match="HTTP 410"):
        await hard.fulfill(
            db=cast(Any, None), order=cast(Any, None), item=item, idempotency_key="k4"
        )


# ---------- check_status reconciliation ----------


async def test_check_status_voucher_branches(_g2b_env: None) -> None:
    mapping = _mapping("voucher")
    task = cast(Any, SimpleNamespace(external_order_id="g1", order_item_id="oi1"))
    db = cast(Any, _FakeDB(_item()))

    gw = _fulfiller(_FakeClient(poll_voucher_delivery=G2bTerminalFailure("expired")), mapping)
    assert (await gw.check_status(db=db, task=task)).outcome == "failed"

    gw = _fulfiller(
        _FakeClient(
            poll_voucher_delivery=VoucherDeliveryResult(status="completed", delivery_items=["C1"])
        ),
        mapping,
    )
    status = await gw.check_status(db=db, task=task)
    assert status.outcome == "succeeded"
    assert status.artifact is not None
    assert status.artifact["code"] == "C1"

    gw = _fulfiller(
        _FakeClient(
            poll_voucher_delivery=VoucherDeliveryResult(status="pending", delivery_items=None)
        ),
        mapping,
    )
    assert (await gw.check_status(db=db, task=task)).outcome == "in_progress"


async def test_check_status_game_branches(_g2b_env: None) -> None:
    mapping = _mapping("game")
    task = cast(Any, SimpleNamespace(external_order_id="go1", order_item_id="oi1"))
    db = cast(Any, _FakeDB(_item(player_id="p-1")))

    for status_value, expected in (
        ("completed", "succeeded"),
        ("failed", "failed"),
        ("processing", "in_progress"),
    ):
        gw = _fulfiller(
            _FakeClient(
                get_game_order_status=GameOrderStatus(
                    g2b_order_id="go1",
                    status=status_value,  # type: ignore[arg-type]
                    message="msg",
                )
            ),
            mapping,
        )
        assert (await gw.check_status(db=db, task=task)).outcome == expected
