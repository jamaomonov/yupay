"""The manual-review rule (ADR-0047)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from yupay.core.config import Settings, get_settings
from yupay.modules.orders.risk import (
    REASON_GEO_MISMATCH,
    REASON_LARGE_AMOUNT,
    REASON_LIQUID_AMOUNT,
    REASON_NEW_BUYER,
    REASON_ROLLING_SUM,
    REASON_SHARED_IDENTITY,
    REASON_VELOCITY,
    VETO_FOREIGN_COUNTRY,
    VETO_FOREIGN_TIMEZONE,
    GeoContext,
    WindowOrder,
    _amount_reason,
    _csv,
    _effective_threshold,
    _gather,
    _geo_reason,
    _is_trusted_buyer,
    _liquid_amount_reason,
    _new_buyer_reason,
    _targets_from,
    _veto_decision,
    _window_reason,
    hold_for_review,
    precharge_veto,
    review_reason,
)


def _settings(threshold: str, *, jitter: bool = True) -> Settings:
    base = get_settings().model_dump()
    base["manual_review_threshold_usd"] = Decimal(threshold)
    base["risk_jitter"] = jitter
    return Settings(**base)


def _order(total_usd: str, *, order_id: str = "0192aaaa-bbbb-cccc-dddd-eeeeffff0000") -> Any:
    return cast("Any", SimpleNamespace(id=order_id, total_usd=Decimal(total_usd)))


def test_an_ordinary_order_is_fulfilled_automatically() -> None:
    # The median production order is about $1. Holding those would replace an
    # automatic service with a manual one and lose the product.
    assert _amount_reason(_order("1.15"), _settings("40", jitter=False)) is None
    assert _amount_reason(_order("11.00"), _settings("40", jitter=False)) is None


def test_a_large_order_is_held() -> None:
    # $202 is the real order this rule was written after: paid, failed two
    # seconds later, and it was also the largest the platform had ever taken.
    assert _amount_reason(_order("202.00"), _settings("40", jitter=False)) == REASON_LARGE_AMOUNT


def test_the_threshold_itself_is_held_not_let_through() -> None:
    """``>=``, not ``>``. An operator setting the limit to 40 means "40 is big
    enough to look at", and off-by-one on a money control is not a detail."""
    assert _amount_reason(_order("40.00"), _settings("40", jitter=False)) == REASON_LARGE_AMOUNT
    assert _amount_reason(_order("39.99"), _settings("40", jitter=False)) is None


def test_zero_disables_the_rule() -> None:
    # An escape hatch that does not need a code change: if the hold ever gets in
    # the way at 3am, it can be turned off from the environment.
    assert _amount_reason(_order("10000"), _settings("0", jitter=False)) is None


def test_jitter_stays_inside_its_band_and_is_stable() -> None:
    cfg = _settings("40")  # risk_jitter left True here
    t1 = _effective_threshold("0192aaaa-bbbb-cccc-dddd-eeeeffff0001", cfg)
    assert t1 == _effective_threshold("0192aaaa-bbbb-cccc-dddd-eeeeffff0001", cfg)
    assert Decimal("24") <= t1 < Decimal("40")  # [0.6, 1.0) x base


def test_jitter_off_means_the_flat_threshold() -> None:
    cfg = _settings("40", jitter=False)
    assert _effective_threshold("any-id", cfg) == Decimal("40")


# ---------- window rules (rolling sum + velocity) ----------


def _cfg(
    sum24: str = "25",
    sum7d: str = "60",
    velocity: int = 5,
    buyers: int = 3,
    liquid: str = "roblox,telegram-stars,steam",
    home: str = "Asia/Tashkent,Asia/Samarkand",
    home_countries: str = "UZ",
    veto: bool = True,
) -> Settings:
    base = get_settings().model_dump()
    base.update(
        risk_sum_24h_usd=Decimal(sum24),
        risk_sum_7d_usd=Decimal(sum7d),
        risk_velocity_24h=velocity,
        risk_distinct_buyers_7d=buyers,
        risk_liquid_brands=liquid,
        risk_home_timezones=home,
        risk_home_countries=home_countries,
        risk_precharge_veto=veto,
        risk_jitter=False,
    )
    return Settings(**base)


_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _wo(
    minutes_ago: int,
    usd: str,
    *,
    buyer: str | None = "me@x.com",
    ip: str | None = None,
    device: str | None = None,
    targets: set[str] | None = None,
) -> WindowOrder:
    return WindowOrder(
        id=f"o-{minutes_ago}-{usd}",
        paid_at=_NOW - timedelta(minutes=minutes_ago),
        total_usd=Decimal(usd),
        buyer=buyer,
        ip=ip,
        device=device,
        targets=frozenset(targets or ()),
    )


def test_rolling_sum_24h_holds_the_order_that_crosses_the_cap() -> None:
    # Ten $18 Roblox orders was the real attack; three $11 is the same move
    # under the lowered threshold. Sum includes the current order.
    recent = [_wo(60, "11"), _wo(120, "11")]  # same buyer
    assert _window_reason(_wo(0, "11"), recent, _cfg()) == REASON_ROLLING_SUM


def test_sum_counts_any_shared_key_not_only_buyer() -> None:
    recent = [
        _wo(60, "11", buyer="a@x.com", ip="203.0.113.7"),
        _wo(120, "11", buyer="b@x.com", ip="203.0.113.7"),
    ]
    current = _wo(0, "11", buyer="c@x.com", ip="203.0.113.7")
    assert _window_reason(current, recent, _cfg()) == REASON_ROLLING_SUM


def test_a_neighbour_sharing_nothing_is_invisible() -> None:
    recent = [_wo(60, "1000", buyer="stranger@x.com", ip="198.51.100.1", device="ffff")]
    assert (
        _window_reason(
            _wo(0, "2", buyer="me@x.com", ip="203.0.113.7", device="aaaa"), recent, _cfg()
        )
        is None
    )


def test_velocity_holds_the_sixth_order_in_a_day() -> None:
    recent = [_wo(i * 10, "1") for i in range(1, 6)]  # five paid, same buyer
    assert _window_reason(_wo(0, "1"), recent, _cfg()) == REASON_VELOCITY


def test_the_7d_cap_catches_a_slow_drip() -> None:
    recent = [_wo(60 * 24 * d, "9") for d in range(1, 7)]  # $9/day for 6 days = $54
    assert _window_reason(_wo(0, "9"), recent, _cfg()) == REASON_ROLLING_SUM  # 63 >= 60


def test_zeroes_disable_each_window_rule() -> None:
    cfg = _cfg(sum24="0", sum7d="0", velocity=0)
    recent = [_wo(10, "500") for _ in range(20)]
    assert _window_reason(_wo(0, "500"), recent, cfg) is None


def test_target_account_links_orders_with_nothing_else_shared() -> None:
    # The 7-orders-to-one-Stars-username pattern: buyers, IPs, devices all
    # differ; the destination does not.
    recent = [
        _wo(60, "11", buyer="a@x.com", ip="203.0.113.1", device="aa", targets={"durov"}),
        _wo(90, "11", buyer="b@x.com", ip="203.0.113.2", device="bb", targets={"durov"}),
    ]
    current = _wo(0, "11", buyer="c@x.com", ip="203.0.113.3", device="cc", targets={"durov"})
    assert _window_reason(current, recent, _cfg()) == REASON_ROLLING_SUM


# ---------- _csv ----------


def test_csv_lowercases_trims_and_drops_empties() -> None:
    assert _csv(" Roblox, telegram-stars ,,STEAM") == frozenset(
        {"roblox", "telegram-stars", "steam"}
    )
    assert _csv("") == frozenset()


# ---------- shared identity (rule 4) ----------


def test_one_device_serving_three_buyers_is_held() -> None:
    recent = [
        _wo(60, "1", buyer="a@x.com", device="dd"),
        _wo(90, "1", buyer="b@x.com", device="dd"),
    ]
    assert (
        _window_reason(_wo(0, "1", buyer="c@x.com", device="dd"), recent, _cfg())
        == REASON_SHARED_IDENTITY
    )


def test_one_buyer_on_two_devices_is_not_shared_identity() -> None:
    # A person with a phone and a laptop is not a fraud ring.
    recent = [
        _wo(60, "1", buyer="a@x.com", device="d1"),
        _wo(90, "1", buyer="a@x.com", device="d2"),
    ]
    assert _window_reason(_wo(0, "1", buyer="a@x.com", device="d3"), recent, _cfg()) is None


# ---------- geo mismatch (rule 5) ----------


def test_guest_liquid_brand_foreign_tz_is_held() -> None:
    assert _geo_reason(True, frozenset({"roblox"}), "Europe/Kiev", _cfg()) == REASON_GEO_MISMATCH


def test_signed_in_or_home_tz_or_illiquid_brand_passes() -> None:
    cfg = _cfg()
    assert _geo_reason(False, frozenset({"roblox"}), "Europe/Kiev", cfg) is None
    assert _geo_reason(True, frozenset({"roblox"}), "Asia/Tashkent", cfg) is None
    assert _geo_reason(True, frozenset({"free-fire"}), "Europe/Kiev", cfg) is None
    assert _geo_reason(True, frozenset({"roblox"}), None, cfg) is None  # no tz = no claim
    assert (
        _geo_reason(True, frozenset({"free-fire", "roblox"}), "Europe/Kiev", cfg)
        == REASON_GEO_MISMATCH
    )  # any liquid item


def test_empty_lists_disable_the_geo_rule() -> None:
    assert _geo_reason(True, frozenset({"roblox"}), "Europe/Kiev", _cfg(liquid="", home="")) is None


def test_an_empty_home_list_alone_also_disables_the_geo_rule() -> None:
    # Distinct from the case above: the brand IS liquid here, so this only
    # passes through `_geo_reason`'s later `if not home` branch rather than
    # its earlier `if not liquid` one.
    assert _geo_reason(True, frozenset({"roblox"}), "Europe/Kiev", _cfg(home="")) is None


# ---------- _targets_from ----------


def test_targets_from_cleans_and_skips_non_strings_and_empties() -> None:
    assert _targets_from(
        {
            "username": " @Durov ",
            "note": "",
            "amount": 5,  # not a string -- ignored, not a target
            "handle": "@Durov",  # same account, different casing/whitespace
        }
    ) == frozenset({"durov"})
    assert _targets_from({}) == frozenset()


def test_targets_from_skips_fields_that_name_a_thing_rather_than_a_person() -> None:
    """A shared game server is not a shared identity.

    Measured on production: `server` carried 142 values across 62 distinct
    ones in 180 days, so two strangers who happen to play Mobile Legends on
    server 15180 were linked into one actor and their spending summed by the
    rolling-sum rule. The catalog keys are the same mistake waiting to scale —
    every buyer of one Steam game shares its `app_id`.
    """
    assert _targets_from(
        {
            "player_id": "10028686281",
            "server": "15180",
            "app_id": "4890090",
            "package_name": "Starfall Command",
            "region": "CIS",
        }
    ) == frozenset({"10028686281"})
    # An order carrying nothing but shared metadata links to nobody.
    assert _targets_from({"server": "15180", "region_code": "ge"}) == frozenset()


# ---------- review_reason: rule 1 short-circuits before the gather ----------


async def test_review_reason_returns_the_amount_reason_without_touching_the_db() -> None:
    # `db` is never awaited on this path -- an object with no `.execute` at
    # all still has to work, which is the point being proven.
    settings = _settings("40", jitter=False)
    reason = await review_reason(cast("Any", object()), _order("202.00"), settings=settings)
    assert reason == REASON_LARGE_AMOUNT


# ---------- _gather: a broken query degrades to rule 1 alone ----------


class _NestedTransaction:
    """Trivial async context manager standing in for what
    ``AsyncSession.begin_nested()`` returns -- just enough of the SAVEPOINT
    protocol for ``async with db.begin_nested():`` to work, not the real
    ``AsyncSessionTransaction`` API.
    """

    async def __aenter__(self) -> _NestedTransaction:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _ExplodingDB:
    """Stands in for a session whose SAVEPOINT opens fine but a query inside
    it blows up -- a Python-level failure (a bad ORM call, an unexpected
    data shape) raised while queries are running under the savepoint.

    Contrast ``_ExplodingSavepointDB`` below, which models a DB-level
    failure (a statement/lock timeout, a dropped connection) that aborts the
    SAVEPOINT itself before any query runs -- the exact failure class the
    ``async with db.begin_nested():`` wrapping (finding 1) exists for: without
    it, this class of failure would poison the caller's transaction instead
    of staying confined to ``_gather``.

    Either way, ``_gather`` must never raise -- a broken risk query has to
    degrade to the amount rule alone rather than block a paid order's
    fulfilment.
    """

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    async def execute(self, *args: object, **kwargs: object) -> Any:
        raise RuntimeError("boom")


class _ExplodingSavepointDB:
    """Stands in for a session whose SAVEPOINT itself fails to open.

    Models a DB-level abort (statement/lock timeout, connection reset)
    that happens before ``_gather`` runs a single SELECT -- as opposed to
    ``_ExplodingDB`` above, which models a failure inside a query already
    running under a successfully-opened savepoint. Both failure classes
    must degrade to the same neutral context.
    """

    def begin_nested(self) -> _NestedTransaction:
        raise RuntimeError("savepoint boom")

    async def execute(self, *args: object, **kwargs: object) -> Any:
        raise AssertionError("must not be reached: begin_nested already raised")


def _order_for_gather(order_id: str) -> Any:
    return cast(
        "Any",
        SimpleNamespace(
            id=order_id,
            paid_at=_NOW,
            total_usd=Decimal("11"),
            user_id=None,
            guest_email="me@x.com",
        ),
    )


async def test_gather_degrades_to_neutral_context_when_a_query_fails() -> None:
    """Python-level failure inside the savepoint (see ``_ExplodingDB``)."""
    order = _order_for_gather("0192aaaa-bbbb-cccc-dddd-eeeeffff0003")
    current, recent, geo = await _gather(cast("Any", _ExplodingDB()), order, _cfg())
    assert current.id == order.id
    assert current.buyer == "me@x.com"
    assert current.ip is None
    assert current.device is None
    assert current.targets == frozenset()
    assert recent == []
    assert geo == GeoContext(is_guest=False, brand_slugs=frozenset(), timezone=None)


async def test_gather_degrades_to_neutral_context_when_the_savepoint_itself_fails() -> None:
    """DB-level failure opening the savepoint (see ``_ExplodingSavepointDB``).

    Without the ``async with db.begin_nested():`` wrapping, a failure this
    early would still be caught by ``_gather``'s ``try/except`` -- the
    regression this guards against is not "does ``_gather`` raise" but "does
    the poisoned transaction survive to the caller", which a unit test with a
    fake session can't observe directly. This test instead pins the
    contract ``_gather`` promises regardless: even a failure before any
    SELECT runs still degrades to the same neutral context, never propagates.
    """
    order = _order_for_gather("0192aaaa-bbbb-cccc-dddd-eeeeffff0005")
    current, recent, geo = await _gather(cast("Any", _ExplodingSavepointDB()), order, _cfg())
    assert current.id == order.id
    assert current.buyer == "me@x.com"
    assert current.ip is None
    assert current.device is None
    assert current.targets == frozenset()
    assert recent == []
    assert geo == GeoContext(is_guest=False, brand_slugs=frozenset(), timezone=None)


# ---------- precharge veto: _veto_decision (Task 2, ADR-0063) ----------


def test_foreign_country_vetoes_a_guest() -> None:
    assert _veto_decision(False, "NL", None, _cfg()) == VETO_FOREIGN_COUNTRY


def test_home_country_passes_whatever_the_timezone_says() -> None:
    # Country is the network's word, timezone the browser's; when both are
    # present the network wins — a VPN into UZ with a Kyiv clock is for the
    # post-payment hold to worry about, not a pre-charge refusal.
    assert _veto_decision(False, "UZ", "Europe/Kiev", _cfg()) is None


def test_timezone_is_only_a_fallback() -> None:
    assert _veto_decision(False, None, "Europe/Kiev", _cfg()) == VETO_FOREIGN_TIMEZONE
    assert _veto_decision(False, None, "Asia/Tashkent", _cfg()) is None


def test_no_signals_no_claim() -> None:
    assert _veto_decision(False, None, None, _cfg()) is None


def test_trusted_buyer_is_exempt() -> None:
    assert _veto_decision(True, "NL", "Europe/Amsterdam", _cfg()) is None


def test_tor_and_unknown_sentinels_veto() -> None:
    # T1/XX are never in a home list; they fall out of the same comparison.
    assert _veto_decision(False, "T1", None, _cfg()) == VETO_FOREIGN_COUNTRY
    assert _veto_decision(False, "XX", None, _cfg()) == VETO_FOREIGN_COUNTRY


def test_empty_home_list_and_kill_switch_disable() -> None:
    assert _veto_decision(False, "NL", None, _cfg(home_countries="")) is None
    assert _veto_decision(False, "NL", "Europe/Kiev", _cfg(veto=False)) is None


# ---------- precharge veto: _is_trusted_buyer / precharge_veto wrapper ----------


async def test_is_trusted_buyer_is_false_for_a_guest_without_touching_the_db() -> None:
    # `user_id is None` is decided before any query — an object with no
    # `.execute` at all still has to work, which is the point being proven.
    assert await _is_trusted_buyer(cast("Any", object()), None) is False


async def test_precharge_veto_returns_none_for_wallet_topups_without_touching_the_db() -> None:
    # The purpose gate runs before the savepoint and before any query — an
    # object with no `.begin_nested`/`.execute` at all still has to work.
    order = cast(
        "Any",
        SimpleNamespace(
            id="0192aaaa-bbbb-cccc-dddd-eeeeffff0010",
            purpose="wallet_topup",
            user_id=None,
        ),
    )
    assert await precharge_veto(cast("Any", object()), order, settings=_cfg()) is None


async def test_precharge_veto_fails_open_when_the_db_explodes() -> None:
    order = cast(
        "Any",
        SimpleNamespace(
            id="0192aaaa-bbbb-cccc-dddd-eeeeffff0011",
            purpose="catalog",
            user_id=None,
        ),
    )
    reason = await precharge_veto(cast("Any", _ExplodingDB()), order, settings=_cfg())
    assert reason is None


# ---------- hold_for_review's detail payload ----------


class _FakeDB:
    """Just enough of ``AsyncSession`` for ``hold_for_review``: ``.add()``."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


class _RecordedEvent:
    """Stands in for ``OrderEvent`` so this stays a real unit test.

    Constructing the actual SQLAlchemy ``OrderEvent`` triggers mapper
    configuration for the whole ``Order`` graph, including its viewonly
    ``payments`` relationship — which resolves the string ``"Payment"`` only
    if ``yupay.modules.payments.models`` has already been imported somewhere
    in the process. In this file it has not, and a failed mapper configure
    poisons the shared SQLAlchemy registry for every later test in the same
    run, including the unrelated integration tests in this test session. What
    is under test here is ``hold_for_review``'s payload-merging, not
    SQLAlchemy — so it is stubbed out rather than risking that.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.payload: dict[str, Any] = kwargs["payload"]


class _FakeRedis:
    async def set(self, *args: object, **kwargs: object) -> bool:
        return True


def _held_order(order_id: str = "0192aaaa-bbbb-cccc-dddd-eeeeffff0002") -> Any:
    return cast(
        "Any",
        SimpleNamespace(
            id=order_id,
            total_usd=Decimal("11"),
            total_charged=Decimal("11"),
            currency="USD",
            paid_at=None,
        ),
    )


async def test_detail_counts_merge_into_the_event_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The watchdog pre-arm and the admin alert are already wrapped in
    # ``contextlib.suppress`` by ``hold_for_review`` itself; these stubs only
    # keep the test from making a real network call, not from a real one
    # failing.
    import yupay.modules.orders.risk as risk_mod
    from yupay.modules.notifications import alerts as alerts_mod

    monkeypatch.setattr(risk_mod, "OrderEvent", _RecordedEvent)
    monkeypatch.setattr(risk_mod, "get_redis", _FakeRedis)

    sent: list[str] = []

    async def _fake_alert(text: str, *, kind: str = "") -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(alerts_mod, "send_admin_alert", _fake_alert)

    db = _FakeDB()
    await hold_for_review(
        cast("Any", db),
        order=_held_order(),
        reason=REASON_SHARED_IDENTITY,
        detail={"linked_orders_24h": 5},
    )

    assert len(db.added) == 1
    payload = db.added[0].payload
    assert payload["reason"] == REASON_SHARED_IDENTITY
    assert payload["linked_orders_24h"] == 5
    # Counts only — the whole point of `detail` is that it can never carry an
    # identity, so nothing that looks like one belongs in the payload.
    assert set(payload) == {"reason", "total_usd", "linked_orders_24h"}


async def test_no_detail_leaves_the_payload_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yupay.modules.orders.risk as risk_mod
    from yupay.modules.notifications import alerts as alerts_mod

    monkeypatch.setattr(risk_mod, "OrderEvent", _RecordedEvent)
    monkeypatch.setattr(risk_mod, "get_redis", _FakeRedis)

    async def _fake_alert(text: str, *, kind: str = "") -> bool:
        return True

    monkeypatch.setattr(alerts_mod, "send_admin_alert", _fake_alert)

    db = _FakeDB()
    await hold_for_review(cast("Any", db), order=_held_order(), reason=REASON_SHARED_IDENTITY)

    assert set(db.added[0].payload) == {"reason", "total_usd"}


# ---------- Click-agreed rules of 2026-09-02: liquid threshold, new buyer, night


def _cfg2(**over: object) -> Settings:
    base = get_settings().model_dump()
    base.update(
        risk_jitter=False,
        risk_liquid_brands="roblox,telegram-stars,steam",
        manual_review_threshold_usd=Decimal("100"),
        risk_liquid_review_threshold_usd=Decimal("0"),
        risk_new_buyer_velocity_24h=0,
        risk_new_buyer_sum_24h_usd=Decimal("0"),
        risk_new_buyer_age_days=7,
        risk_night_start_hour=22,
        risk_night_end_hour=7,
        risk_night_threshold_multiplier=Decimal("1"),
    )
    base.update(over)
    return Settings(**base)


def _noon() -> datetime:
    return datetime(2026, 9, 2, 7, 0, tzinfo=UTC)  # 12:00 in Tashkent (UTC+5)


def _night() -> datetime:
    return datetime(2026, 9, 2, 20, 0, tzinfo=UTC)  # 01:00 in Tashkent


def test_liquid_brands_get_their_own_lower_threshold() -> None:
    # Click's rule 2: Stars above the typical purchase go to manual release
    # even while the global threshold would wave them through.
    cfg = _cfg2(risk_liquid_review_threshold_usd=Decimal("30"))
    held = _liquid_amount_reason(_order("40.00"), frozenset({"telegram-stars"}), cfg, at=_noon())
    assert held == REASON_LIQUID_AMOUNT
    assert (
        _liquid_amount_reason(_order("40.00"), frozenset({"pubg-mobile"}), cfg, at=_noon()) is None
    )
    assert (
        _liquid_amount_reason(_order("25.00"), frozenset({"telegram-stars"}), cfg, at=_noon())
        is None
    )


def test_night_halves_the_thresholds() -> None:
    # Click's rule 4: the fraud waves ran at night; the same amount that
    # passes at noon is held at 01:00 Tashkent.
    cfg = _cfg2(
        risk_liquid_review_threshold_usd=Decimal("30"),
        risk_night_threshold_multiplier=Decimal("0.5"),
    )
    brands = frozenset({"telegram-stars"})
    assert _liquid_amount_reason(_order("20.00"), brands, cfg, at=_noon()) is None
    assert _liquid_amount_reason(_order("20.00"), brands, cfg, at=_night()) == (
        REASON_LIQUID_AMOUNT
    )


def test_a_new_buyer_hits_the_velocity_lid_where_a_regular_does_not() -> None:
    # Click's rule 3: 3 purchases per 24h for identities we first saw today.
    cfg = _cfg2(risk_new_buyer_velocity_24h=3)
    current = WindowOrder(
        id="01aa0000-0000-7000-8000-00000000000a",
        paid_at=_NOW,
        total_usd=Decimal("11"),
        buyer="me@x.com",
        ip=None,
        device=None,
        targets=frozenset(),
    )
    fresh = [
        WindowOrder(
            id=f"01aa0000-0000-7000-8000-00000000000{i}",
            paid_at=_NOW - timedelta(hours=i + 1),
            total_usd=Decimal("2"),
            buyer="me@x.com",
            ip=None,
            device=None,
            targets=frozenset(),
        )
        for i in range(3)
    ]
    got = _new_buyer_reason(current, fresh, cfg)
    assert got == REASON_NEW_BUYER

    # The same shape with one linked order older than the age window is a
    # regular customer — untouched.
    seasoned = [
        *fresh,
        WindowOrder(
            id="01aa0000-0000-7000-8000-0000000000ff",
            paid_at=_NOW - timedelta(days=30),
            total_usd=Decimal("2"),
            buyer="me@x.com",
            ip=None,
            device=None,
            targets=frozenset(),
        ),
    ]
    assert _new_buyer_reason(current, seasoned, cfg) is None


def test_a_new_buyer_sum_cap_holds_the_third_small_order() -> None:
    cfg = _cfg2(risk_new_buyer_sum_24h_usd=Decimal("8"))
    current = WindowOrder(
        id="01aa0000-0000-7000-8000-00000000000b",
        paid_at=_NOW,
        total_usd=Decimal("11"),
        buyer="me@x.com",
        ip=None,
        device=None,
        targets=frozenset(),
    )
    linked = [
        WindowOrder(
            id="01aa0000-0000-7000-8000-0000000000aa",
            paid_at=_NOW - timedelta(hours=2),
            total_usd=Decimal("4"),
            buyer="me@x.com",
            ip=None,
            device=None,
            targets=frozenset(),
        )
    ]
    # 11 + 4 >= 8 → held; the identity is brand new.
    assert _new_buyer_reason(current, linked, cfg) == REASON_NEW_BUYER
    assert _new_buyer_reason(current, [], _cfg2(risk_new_buyer_sum_24h_usd=Decimal("20"))) is None
