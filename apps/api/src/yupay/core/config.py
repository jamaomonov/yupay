"""Application configuration.

Reads from environment variables (and from ``.env`` files in development) via
``pydantic-settings``. The settings object is cached for the process lifetime via
``functools.lru_cache``.
"""

from __future__ import annotations

import base64
import binascii
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _maybe_decode_pem(value: str) -> str:
    """Accept either a raw PEM string or its base64-encoded form.

    ``.env`` files don't handle multi-line values well; we let operators paste a
    base64 blob and transparently decode it back to PEM on load.
    """
    if not value:
        return value
    if value.startswith("-----"):
        return value
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return value
    if decoded.startswith("-----"):
        return decoded
    return value


class Settings(BaseSettings):
    """Top-level application settings.

    All fields are read from environment variables. Names are case-insensitive.
    Sensitive defaults are *never* hard-coded — the app will refuse to start without them.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # --- runtime ---
    environment: Literal["dev", "staging", "prod", "test"] = Field(default="dev")
    debug: bool = Field(default=False)
    service_name: str = Field(default="yupay-api")
    base_url: str = Field(default="http://localhost:8000")
    web_base_url: str = Field(
        default="",
        description=(
            "Public base URL of the web storefront (e.g. https://yupay.uz). "
            "Used to construct verify/reset links in transactional emails. "
            "Falls back to the API's own base_url when empty."
        ),
    )

    # --- data ---
    database_url: str = Field(
        default="postgresql+asyncpg://yupay_app:yupay_app@localhost:5432/yupay",
        description="Async SQLAlchemy URL (postgresql+asyncpg://...)",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- rate limiting ---
    rate_limit_enabled: bool | None = Field(
        default=None,
        description=(
            "Force the global per-IP limiter on/off. Unset (None) means "
            "on everywhere except ENVIRONMENT=test, where the suite would "
            "trip it instantly."
        ),
    )
    rate_limit_default: str = Field(
        default="600/minute",
        description=(
            "Default per-IP limit on every route (slowapi syntax). A coarse "
            "flood-stopper, not a per-endpoint policy: anything that needs a "
            "real limit has its own Redis-backed two-axis guard in "
            "modules/auth/ip_guard.py, and provider callbacks are exempt "
            "entirely. Raised from 120/minute, which was sized for form posts "
            "and throttled ordinary reads — prerendering the storefront fetches "
            "every brand, product and review across three locales, hundreds of "
            "requests from one address in half a minute, and it failed a "
            "production image build. A carrier NAT or a crawler produces the "
            "same shape."
        ),
    )

    # --- auth ---
    jwt_public_key: str = Field(default="")
    jwt_private_key: str = Field(default="")
    jwt_kid: str = Field(default="v1", description="JWT key id (kid header)")
    jwt_issuer: str = Field(default="yupay")
    jwt_access_ttl_seconds: int = Field(default=900)  # 15 min
    jwt_refresh_ttl_seconds: int = Field(default=60 * 60 * 24 * 30)  # 30 days
    jwt_guest_ttl_seconds: int = Field(default=60 * 30)  # 30 min for guest checkout
    # Order-scoped guest access to delivered codes (magic-link in the delivered
    # email). Longer than checkout because the buyer may open the order days
    # later; the token unlocks only that one order's codes — see ADR-0042.
    jwt_guest_order_ttl_seconds: int = Field(default=60 * 60 * 24 * 7)  # 7 days
    # Affiliate program. See
    # docs/superpowers/specs/2026-08-27-affiliate-program-design.md.
    #: Days between an order being delivered and its commission becoming
    #: withdrawable. Covers the acquirers' dispute window without making a
    #: partner wait a month for a first payout.
    affiliate_hold_days: int = Field(default=14)
    #: How often the accrual sweep runs. Freshness costs nothing here — the
    #: hold period dominates — but the panel should never look stalled.
    affiliate_sweep_minutes: int = Field(default=5)
    #: Rows processed per sweep pass, per step. A backlog drains over several
    #: passes rather than in one long transaction.
    affiliate_sweep_batch: int = Field(default=500)
    #: Smallest withdrawal, in the partner's own currency. Each payout is a
    #: manual bank transfer, so there is a floor. Estimated, not measured —
    #: revisit once real partner volumes exist.
    affiliate_min_payout: Decimal = Field(default=Decimal("50000"))
    #: Partner panel token lifetimes. Same shape as the buyer's — short
    #: access, long rotating refresh — but separately configurable, because
    #: a partner session guards money going out rather than money coming in.
    affiliate_access_ttl_seconds: int = Field(default=900)  # 15 min
    affiliate_refresh_ttl_seconds: int = Field(default=60 * 60 * 24 * 30)  # 30 days
    # --- Merchant cabinet (spec §11) ---
    # The same pair for a reseller's operator. Matched to the affiliate panel's
    # numbers rather than to the storefront's: both are a person working in a
    # back office on their own machine, not a shopper on a phone, and a
    # 15-minute access token with a 30-day refresh is what that shape already
    # uses here.
    merchant_access_ttl_seconds: int = Field(default=900)  # 15 min
    merchant_refresh_ttl_seconds: int = Field(default=60 * 60 * 24 * 30)  # 30 days
    #: How long a cabinet email-confirmation link stays usable. Deliberately
    #: shorter than the affiliate password-reset window is long: a merchant who
    #: misses it registers again, which costs them a minute and us nothing.
    merchant_confirm_ttl_seconds: int = Field(default=60 * 60 * 24)  # 24 h
    #: Where the cabinet lives, for the confirmation link. Empty disables
    #: registration mail rather than sending a link to nowhere — a confirmation
    #: a merchant cannot complete is worse than a clear failure at signup.
    merchant_cabinet_url: str = Field(default="")
    #: Where the partner site lives. The approval email links into it, so an
    #: empty value would send a partner a href that goes nowhere.
    partners_base_url: str = Field(default="https://partners.yupay.uz")

    jwt_ws_ttl_seconds: int = Field(default=60)  # 60 s for WS handshake
    jwt_email_token_ttl_seconds: int = Field(default=60 * 30)  # 30 min for verify/reset links
    auth_email_pepper: str = Field(
        default="",
        description="Pepper mixed into SHA-256 email hashes embedded in guest JWTs.",
    )
    telegram_init_data_ttl_seconds: int = Field(default=60 * 60 * 24)  # 24h

    # --- dev-only admin login ---
    # When enabled, ``POST /api/v1/auth/admin-dev`` accepts a hardcoded login/password
    # and mints an admin JWT. Useful before BotFather domains are set up. NEVER enable
    # in prod — the setting is force-disabled when ``environment == "prod"``.
    admin_dev_login_enabled: bool = Field(default=False)
    admin_dev_login: str = Field(default="admin")
    admin_dev_password: str = Field(default="admin")

    @field_validator("jwt_private_key", "jwt_public_key", mode="after")
    @classmethod
    def _decode_pem(cls, v: str) -> str:
        """Accept base64-encoded PEM blobs (single-line, ``.env``-friendly)."""
        return _maybe_decode_pem(v)

    # --- telegram ---
    telegram_bot_token: str = Field(default="")
    # Separate bot for the admin SPA's Login Widget. The widget is domain-bound
    # via BotFather /setdomain, and a bot allows only one login domain — so the
    # admin panel (admin.yupay.uz) needs its own bot. Empty => falls back to
    # ``telegram_bot_token`` so a single-bot dev/staging setup keeps working.
    admin_telegram_bot_token: str = Field(default="")
    # Outbound proxy for the Telegram Bot API (api.telegram.org). Needed when the
    # host can't reach Telegram directly (e.g. from RU). HTTP proxy, e.g.
    # ``http://user:pass@host:port``. Empty => connect directly (default).
    telegram_proxy_url: str = Field(default="")

    # --- Email (Resend) ---
    resend_api_key: str = Field(default="")
    email_from: str = Field(default="noreply@yupay.uz")
    email_from_name: str = Field(default="YuPay")
    email_logo_url: str = Field(
        default="",
        description=(
            "Absolute, publicly reachable URL of the brand logo PNG shown in the "
            "header of transactional emails (email clients don't render SVG). When "
            "empty, falls back to ``{web_base_url}/logo/email-logo.png``; if that is "
            "also unavailable the emails render a text-only wordmark."
        ),
    )

    # --- Auth IP guard (lightweight; full rate limiting is a separate concern) ---
    auth_ip_guard_max: int = Field(
        default=10, description="Max sensitive auth hits per window per IP."
    )
    auth_ip_guard_window_seconds: int = Field(default=60)
    auth_ip_guard_subject_max: int = Field(
        default=10,
        description=(
            "Max attempts per window against ONE identity (ip + email) on the "
            "credential endpoints. This is the axis that actually blunts brute "
            "force, which is what lets the per-IP numbers below be sized for a "
            "carrier NAT instead of for a single attacker."
        ),
    )
    auth_ip_guard_bucket_max: dict[str, int] = Field(
        default_factory=lambda: {
            # Sized for the crowd behind one mobile-carrier address, not for one
            # attacker — see auth_ip_guard_subject_max for the other axis.
            "check_player": 200,
            # A campaign promo code is handed to a crowd on purpose, and one
            # user can only redeem it once (uq_promo_redemptions_code_user), so
            # this bucket guards throughput, not a secret.
            "promo-redeem": 120,
            "register": 60,
            "login": 60,
            "forgot": 60,
            "resend-verification": 60,
            # Guests re-fetching codes they already paid for.
            "code-access": 60,
            # Sixty a minute is far above any person and far below a script.
            "order-create": 60,
            # Affiliate. The preview is the one that needs room: it is an
            # advisory lookup a buyer runs while filling in checkout, and Uzbek
            # carriers put many subscribers behind one address — the same
            # reasoning that sized `check_player`. Brute force is blunted on
            # the other axis, which keys on the signed-in buyer.
            "affiliate-preview": 120,
            # Applying and signing in are rare per person, but a shared address
            # must not lock out the second partner in an office.
            "affiliate-apply": 30,
            "affiliate-login": 30,
            "affiliate-setpw": 30,
            # Same reasoning as `check_player`/`affiliate-preview`: an advisory
            # pre-purchase lookup a buyer runs while pasting in a recipient's
            # Steam link, shared collectively by a whole carrier's subscribers
            # on one address. The Redis cache (`gifts:steam_profile:*`, 6h)
            # already makes a repeat of the same link free, so this only
            # bounds distinct links from one address.
            "gifts-steam-profile": 120,
            # The machine API (/merchant/v1). Sixty times the default
            # credential bucket because the caller is a server, not a person:
            # a reseller's backend legitimately fires a burst of order
            # creations and status polls from ONE address, and ten a minute
            # would break the integration on day one. 600 matches
            # ``rate_limit_default`` (the coarse per-IP, per-endpoint limiter
            # in bootstrap), so neither tier surprises the other. Brute force
            # is not the threat model here — the credential is a 256-bit
            # secret compared with ``compare_digest`` — throughput is, which
            # is why no ``subject`` is passed on this bucket and the
            # per-merchant axis is ``merchant_api_key_rate_max`` below
            # instead.
            "merchant-api": 600,
            # `POST /merchant/v1/validate/player`, and stricter than the
            # prefix above it on purpose (spec §12: "stricter on validate/* —
            # it spends supplier quota"). Every other endpoint there spends
            # only our own database; this one calls G2B or Waxpeer, whose quota
            # we buy and whose rate limit is not ours to raise. 120 is two a
            # second sustained — comfortably above one check per order for a
            # reseller polling and ordering all day, and a fifth of what the
            # prefix allows.
            #
            # This is the per-*address* half only, and on its own it does not
            # bound what one merchant can spend: a caller behind a multi-node
            # egress pool has one of these counters per NAT address, so the
            # ceiling that actually follows the merchant is
            # `merchant_validate_rate_max` below. Keep the two numbers equal
            # unless there is a reason not to. Both fail open on Redis trouble
            # (`ip_guard.hit_counter`), which is the same outage that empties
            # the 300s result cache and the supplier breaker — so a Redis
            # failure removes all three protections at once and the supplier's
            # own limiter is what is left. That is a known and accepted
            # property, not an oversight.
            "merchant-validate": 120,
        },
        description=(
            "Per-bucket overrides for auth_ip_guard_max. The default is written for "
            "brute-force endpoints (login, register, forgot): ten tries a minute is "
            "generous there. The storefront player check is not one of those -- it is "
            "an advisory lookup a customer runs while filling in the order form, and "
            "Uzbek mobile carriers put many subscribers behind one address, so they "
            "spend a shared budget collectively. Values <= 0 are ignored, so a typo "
            "falls back to the default instead of disabling the guard."
        ),
    )
    merchant_api_key_rate_max: int = Field(
        default=600,
        description=(
            "Max /merchant/v1 requests per window per API KEY, the merchant axis "
            "of the machine API's two-axis guard (the IP axis is the "
            "'merchant-api' bucket above). Shares auth_ip_guard_window_seconds, "
            "which is why it lives here and not with the other merchant settings: "
            "widening that window loosens this ceiling by the same factor. Per "
            "key rather than per merchant, so a merchant mid-rotation briefly has "
            "two budgets -- deliberate, since the point is a fair share under "
            "load and not a hard quota. Charged only AFTER the signature "
            "verifies: a key id travels in a plaintext header, and a third party "
            "who reads one must not be able to spend its owner's budget. Forged "
            "traffic is bounded by the IP axis instead."
        ),
    )

    merchant_validate_rate_max: int = Field(
        default=120,
        description=(
            "Max POST /merchant/v1/validate/player calls per window per MERCHANT "
            "-- the axis that matches what the limit is protecting. The bucket "
            "above counts addresses, and the resource being rationed is a "
            "supplier's quota, which a reseller spends per account and not per "
            "egress node: with the IP counter alone, a six-node NAT pool got six "
            "times the budget and the binding constraint fell back to "
            "merchant_api_key_rate_max (600), five times the number the bucket's "
            "own comment advertises. Keyed on merchant_id rather than key_id, "
            "unlike merchant_api_key_rate_max: a fair share of OUR request "
            "capacity may briefly double during a key rotation without hurting "
            "anyone, but a supplier's quota is a real external budget and "
            "rotating a key must not double a merchant's claim on it. Charged in "
            "the handler, after authentication. Shares "
            "auth_ip_guard_window_seconds, so widening that window loosens this "
            "ceiling by the same factor."
        ),
    )

    # --- Review conversion ---
    review_reminder_after_hours: int = Field(
        default=0,
        description=(
            "Hours after delivery before a buyer who has not rated their order gets one "
            "Telegram reminder. 0 = off, which is the default: this messages real "
            "customers, so it is switched on deliberately rather than by deploying. "
            "24 is the intended value -- the delivery message already asks, and it "
            "arrives while the buyer is leaving for the game. Capped by "
            "`PENDING_ASK_MAX_AGE` (14 days) at the far end, by one order per user per "
            "run, and by a 7-day per-user cooldown; see modules/reviews/reminder.py."
        ),
    )

    # --- Manual review of large orders (ADR-0047) ---
    manual_review_threshold_usd: Decimal = Field(
        default=Decimal("40"),
        description=(
            "Orders at or above this amount are held after payment instead of being "
            "fulfilled automatically. Denominated in USD because `orders.total_usd` is "
            "stable while the som amount moves with the rate. Re-measured 2026-09-14 "
            "over 706 paid orders: median $2.74, p90 $20, p95 $38, p99 $146, and "
            "12 030 UZS to the dollar, so 40 is ≈ 481 000 UZS. **This is not the "
            "number that binds** — `risk_jitter` spreads the effective threshold over "
            "[0.6x, 1x) and `risk_night_threshold_multiplier` used to halve that again "
            "at night, so a configured 24 was holding $7.20 orders. See "
            "docs/runbooks/order-held-for-review.md. Set to 0 to disable."
        ),
    )
    risk_sum_24h_usd: Decimal = Field(
        default=Decimal("25"),
        description=(
            "Orders sharing an identity (buyer, IP, device, or delivery target) whose "
            "combined total over the trailing 24h reaches this are held, even though no "
            "single order crossed `manual_review_threshold_usd`, because the attack this "
            "rule targets is many small orders rather than one large one. Keep it above "
            "what real customers spend in a day, not below the single-order threshold: "
            "measured 2026-09-14, p95 of a real identity's 24h total is $144, and the "
            "default 25 held 22 orders in 12 days, every one of them delivered. Set to "
            "0 to disable."
        ),
    )
    risk_sum_7d_usd: Decimal = Field(
        default=Decimal("60"),
        description=(
            "Same as `risk_sum_24h_usd` but over a trailing 7 days, to catch a slower "
            "drip that stays under the 24h cap on any given day. Set to 0 to disable."
        ),
    )
    risk_velocity_24h: int = Field(
        default=5,
        description=(
            "Orders sharing an identity whose count over the trailing 24h reaches this "
            "are held, regardless of amount — a burst of many cheap orders is itself a "
            'signal. 5 was chosen as "above the highest observed same-buyer '
            'repeat-purchase count in a day, so ordinary customers never see it"; '
            "production disagreed. Re-measured 2026-09-14: p90 is 4 orders in 24h, p95 "
            "is 6, the busiest real customer reached 12, and the rule held 10 orders in "
            "30 days, all delivered. Set to 0 to disable."
        ),
    )
    risk_distinct_buyers_7d: int = Field(
        default=3,
        description=(
            "Distinct buyer identities sharing another key (IP, device, or delivery "
            "target) over the trailing 7 days that reach this are held — one card or "
            "device paying for several different accounts is a resale pattern, not "
            "coincidence. Set to 0 to disable."
        ),
    )
    risk_liquid_brands: str = Field(
        default="roblox,telegram-stars,steam",
        description=(
            "Comma-separated SKU brand slugs treated as cash-equivalent for the identity "
            "window rules — gift-card and top-up brands that convert to real money "
            "fastest on resale markets, so orders for them are watched more closely. CSV "
            "rather than a list: an operator types `RISK_LIQUID_BRANDS=roblox,steam` "
            "directly into the environment without needing JSON syntax."
        ),
    )
    risk_home_timezones: str = Field(
        default="Asia/Tashkent,Asia/Samarkand",
        description=(
            "Comma-separated IANA timezones treated as the storefront's home market. "
            "Client-hint timezones outside this set are a weak signal that a device is "
            "not where its orders claim to be. CSV for the same reason as "
            "`risk_liquid_brands`."
        ),
    )
    risk_jitter: bool = Field(
        default=True,
        description=(
            "Randomize each order's effective manual-review threshold within a band "
            "below `manual_review_threshold_usd` instead of using one flat cut-off. A "
            "fixed threshold is a number an attacker can probe for and stay just under; "
            "jitter is deterministic per order id, so retries and tests stay stable, but "
            "the boundary is not the same twice. Off in tests that assert an exact "
            "threshold."
        ),
    )
    risk_device_identity: bool = Field(
        default=False,
        description=(
            "Whether `order_evidence.device_hash` counts as an identity for the window "
            "rules (rolling sum, velocity, shared identity). Off by default: measured on "
            "production, this audience's device fingerprint (user-agent + timezone + "
            "locale + screen) is not unique enough on its own — a homogeneous mobile "
            "fleet of identical phones on identical locales already collides two device "
            "hashes across 4 distinct buyers each and two more across 3, exactly rule 4's "
            "`risk_distinct_buyers_7d` default. Enabling it there would hold real, "
            "unrelated customers who happen to share a phone model, not a resale ring. "
            "Run the collision-measurement query in `docs/runbooks/order-held-for-review.md` "
            "against your own traffic before turning this on."
        ),
    )

    # --- Pre-charge geo veto (ADR-0063) ---
    risk_precharge_veto: bool = Field(
        default=True,
        description=(
            "Whether `precharge_veto` refuses a charge before it happens for a guest "
            "or fresh account (no delivered order yet) whose evidence puts them "
            "outside `risk_home_countries`/`risk_home_timezones`. A trusted buyer — "
            "signed in with at least one delivered order — always passes regardless: "
            "registration costs a carder nothing, so the exemption is earned, not "
            "assumed. `False` disables the refusal entirely; the post-payment window "
            "rules above are unaffected and keep running."
        ),
    )
    risk_home_countries: str = Field(
        default="UZ",
        description=(
            "Comma-separated ISO-3166-1 alpha-2 codes treated as the storefront's "
            "home market for the pre-charge veto, matched against "
            "`order_evidence.ip_country` — Cloudflare's edge-resolved country, not a "
            "self-report. CSV for the same reason as `risk_liquid_brands`. Empty "
            "disables the veto whenever a country is known: `_veto_decision` returns "
            "as soon as `country is not None`, so a known country never falls through "
            "to the timezone check. The timezone fallback applies only to orders with "
            "no country at all (`ip_country` is `NULL` — header missing, or a "
            "pre-toggle order)."
        ),
    )
    risk_hold_auto_refund_hours: int = Field(
        default=0,
        description=(
            "How long an order held by `hold_for_review` may sit before a sweep "
            "refunds it automatically instead of waiting on an operator indefinitely "
            "— the hold alert already tells them to act; this is the deadline behind "
            "it. Ships off, like `risk_device_identity`: turning this on day one would "
            "auto-refund the standing held backlog nobody has triaged yet. An operator "
            "works through that backlog first, then arms the sweep with "
            "`RISK_HOLD_AUTO_REFUND_HOURS=24`. `0` also doubles as the fire-drill lever "
            "to fall back to an indefinite hold later."
        ),
    )

    # --- Async fulfilment ---
    fulfilment_async: bool = Field(
        default=False,
        description=(
            "Execute fulfilment in the worker instead of inside the payment "
            "webhook. Off by default: the deploy that ships this must change "
            "production behaviour by zero bytes; the flip is an env change on "
            "the api container only — the worker always drains what exists."
        ),
    )
    fulfilment_poll_seconds: int = Field(
        default=5,
        description=(
            "Worker poll tick. LISTEN/NOTIFY does the real-time work; the "
            "tick only catches notifications lost to a worker restart, so it "
            "can be lazy. One indexed query per tick."
        ),
    )
    fulfilment_concurrency: int = Field(
        default=4,
        ge=1,
        description=(
            "How many drainers the worker runs in parallel, each on its own "
            "DB session. One would mean a single hung supplier call stalls "
            "every order behind it; SKIP LOCKED already keeps their claims "
            "disjoint, so this is a dial with no coordination cost."
        ),
    )

    # --- Merchant outgoing webhooks (M3a) ---
    merchant_webhook_concurrency: int = Field(
        default=2,
        ge=1,
        description=(
            "How many delivery drainers the worker runs in parallel for "
            "`merchant_webhook_deliveries`, each on its own DB session. Same "
            "reasoning as `fulfilment_concurrency` and a separate dial for a "
            "different failure: here the thing that hangs is a merchant's own "
            "server, and one drainer would let a single endpoint sitting on "
            "the 10s budget stall every other reseller's events behind it. "
            "Two attempts to the SAME endpoint still serialise at commit "
            "(both write that merchant's hook row), which is a feature — it "
            "bounds how hard one queue can hit one server."
        ),
    )
    merchant_webhook_disable_after_failures: int = Field(
        default=20,
        ge=1,
        description=(
            "Consecutive failed deliveries before a merchant's webhook is "
            "auto-disabled and their operator is emailed. Counts attempts, "
            "not events, so retries of one dead endpoint reach it: with the "
            "30s-doubling backoff, 20 is roughly two hours of sustained "
            "failure at ordinary volume — long enough not to punish a deploy "
            "window, short enough that nobody reads a week-old backlog. "
            "Reset to 0 by any success and by `PUT /admin/merchants/{id}/"
            "webhook`, which is the whole recovery path."
        ),
    )

    # --- Stuck-order watchdog (ADR-0046) ---
    stuck_order_alert_after_minutes: int = Field(
        default=15,
        description=(
            "How long an order may sit paid-but-undelivered before it is alerted on. "
            "Normal automatic delivery is 1-5 minutes, so 15 is well clear of the happy "
            "path while still catching a failure the same hour it happens."
        ),
    )
    stuck_order_alert_repeat_hours: int = Field(
        default=4,
        description=(
            "How often an already-alerted stuck order is raised again while it stays "
            "unresolved. A single alert is how an order sat for a day: one message "
            "arrives, is missed or forgotten, and nothing ever asks again."
        ),
    )

    # --- Chargeback evidence (ADR-0044) ---
    evidence_retention_days: int = Field(
        default=600,
        description=(
            "Days an order's request-context capture is kept before the purge job "
            "deletes it. Payme's Общие условия п. 6.3.2 require transaction documents "
            "for 540 days; the extra 60 absorb a late dispute landing on day 539 and "
            "the days it then takes to answer. Raising this extends how long unhashed "
            "IPs live — see ADR-0044 before changing it."
        ),
    )

    # Public URL of the miniapp — embedded into the inline ``WebAppInfo``
    # button the bot attaches to /start. Falls back to the dev Caddy host
    # when unset so a fresh checkout boots without env tweaks.
    telegram_miniapp_url: str = Field(default="https://yupay.local/miniapp/")

    # --- fx ---
    fx_supported_quotes: list[str] = Field(default_factory=lambda: ["RUB", "UZS", "USDT"])
    # Preferred provider when a key is set. Free tier supports USD base with ~160
    # currencies; ``{key}`` is the placeholder we substitute at request time.
    fx_exchangerate_api_url: str = Field(
        default="https://v6.exchangerate-api.com/v6/{key}/latest/USD"
    )
    fx_exchangerate_api_key: str = Field(default="")
    fx_primary_url: str = Field(default="https://api.exchangerate.host/latest")
    fx_fallback_url: str = Field(default="https://openexchangerates.org/api/latest.json")
    fx_fallback_api_key: str = Field(default="")
    fx_rates_api_url: str = Field(default="https://api.fxratesapi.com/latest")
    fx_rates_api_key: str = Field(default="")
    fx_crypto_url: str = Field(default="https://api.coingecko.com/api/v3/simple/price")
    fx_cache_fresh_seconds: int = Field(default=15 * 60)
    fx_cache_stale_seconds: int = Field(default=24 * 60 * 60)
    fx_provider_timeout_seconds: float = Field(default=1.5)
    fx_snapshot_max_age_seconds: int = Field(default=5 * 60)

    # --- pricing (fx trust gate) ---
    # Trust gate for rates that set a customer-facing price. A plausible but
    # wrong rate is worse than no rate: we would apply the margin multiplier to
    # it and keep selling. Failing closed costs a sale; failing open costs the
    # difference on every order.
    pricing_fx_max_age_seconds: int = Field(default=6 * 3600)
    pricing_fx_max_deviation_pct: Decimal = Field(default=Decimal("15"))
    pricing_fx_min_rate_uzs: Decimal = Field(default=Decimal("8000"))
    pricing_fx_max_rate_uzs: Decimal = Field(default=Decimal("25000"))
    # Kill-switch: a drop bigger than this (fiat quotes only) puts every
    # *active* payment provider — including wallet — into maintenance and
    # pages ops. Rise is ignored. Recovery is manual. See ADR-0056.
    fx_drop_tripwire_pct: Decimal = Field(default=Decimal("6"))
    fx_drop_watched_quotes: list[str] = Field(default_factory=lambda: ["UZS", "RUB"])
    fx_refresh_interval_minutes: int = Field(default=5)

    # --- merchant B2B pricing (reseller; spec §8.3) ---
    # The only global pricing control on the wholesale price formula (see
    # ``yupay.modules.merchants.pricing``, the one home for that formula): if
    # a computed price is below ``cost * (1 + floor/100)`` the order is
    # rejected with a distinct code. Catches a fat-fingered per-SKU
    # ``b2b_markup_pct`` (e.g. "0.5" typed for "5") and cost spikes a stale
    # markup no longer covers. Read by callers and passed in — the pure
    # pricing functions never read settings themselves.
    merchant_margin_floor_pct: Decimal = Field(default=Decimal("2"))

    # --- observability ---
    sentry_dsn: str | None = Field(default=None)
    sentry_traces_sample_rate: float = Field(default=0.1)
    otlp_endpoint: str | None = Field(default=None)
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    # --- google sign-in ---
    #: OAuth Web client id the GIS button mints ID tokens for. Sign-in is off
    #: (route answers 503-ish RuntimeError-free 401) while empty.
    google_oauth_client_id: str | None = Field(default=None)

    # --- click-agreed antifraud rules (2026-09-02) ---
    #: Rule 2: liquid brands (risk_liquid_brands) get this LOWER manual-review
    #: threshold — Stars above the typical purchase go to manual release even
    #: while manual_review_threshold_usd would wave them through. 0 = off.
    risk_liquid_review_threshold_usd: Decimal = Field(default=Decimal("0"))
    #: Rule 3: identities first seen within risk_new_buyer_age_days are capped
    #: at this many paid orders per rolling 24h; the next goes to manual
    #: release. 0 = off.
    risk_new_buyer_velocity_24h: int = Field(default=0)
    #: Rule 3's amount half: a new identity whose rolling-24h paid total
    #: (current order included) reaches this many USD is held. 0 = off.
    risk_new_buyer_sum_24h_usd: Decimal = Field(default=Decimal("0"))
    #: An identity counts as "new" while its oldest linked order is younger
    #: than this many days.
    risk_new_buyer_age_days: int = Field(default=7)
    #: Rule 4: between these Tashkent hours the review thresholds are
    #: multiplied by risk_night_threshold_multiplier (fraud waves run at
    #: night). Window wraps midnight: start 22, end 7.
    risk_night_start_hour: int = Field(default=22)
    risk_night_end_hour: int = Field(default=7)
    #: 1 = night changes nothing; 0.5 halves the thresholds at night.
    risk_night_threshold_multiplier: Decimal = Field(default=Decimal("1"))
    #: Rule 5: a second copy of every hold alert goes to this chat — the
    #: shared fraud-review group with the payment provider. Empty = off.
    tg_fraud_chat_id: str | None = Field(default=None)

    # --- steam sign-in ---
    #: Steam Web API key (steamcommunity.com/dev/apikey) — used only to fetch
    #: the persona name and avatar after a verified OpenID login. Sign-in
    #: works without it; profiles just come up nameless.
    steam_api_key: str | None = Field(default=None)

    # --- google merchant center feed (ADR-0065) ---
    #: Merchant Center account id (the number in the MC header). Feed is off
    #: while any of the three below is empty — the scheduler job then no-ops.
    merchant_center_account_id: str | None = Field(default=None)
    #: Id of the Merchant API data source ("api v2") products are pushed into.
    merchant_center_data_source_id: str | None = Field(default=None)
    #: Path to the service-account JSON key, mounted as a secret file.
    merchant_center_key_file: str | None = Field(default=None)

    # --- cors ---
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- media storage (Cloudflare R2, S3-compatible) ---
    # The bucket holds publicly served media — brand logos, hero
    # images, product/SKU thumbnails. Reads go through ``cdn.yupay.uz``
    # (custom domain in front of R2); writes are direct from the admin
    # SPA via presigned PUT URLs that this service issues on demand,
    # so large image uploads never touch FastAPI.
    r2_account_id: str = Field(default="")
    r2_access_key_id: str = Field(default="")
    r2_secret_access_key: str = Field(default="")
    r2_bucket_media: str = Field(default="yupay-media")
    r2_public_base_url: str = Field(
        default="https://cdn.yupay.uz",
        description="Public read URL prefix; no trailing slash.",
    )
    r2_presign_ttl_seconds: int = Field(default=300)  # 5 min — plenty for one PUT
    media_max_upload_bytes: int = Field(default=5 * 1024 * 1024)  # 5 MB
    media_allowed_mime: list[str] = Field(
        # No image/svg+xml: SVG is scriptable and served from the public CDN
        # origin (stored XSS). See storage.service._IMAGE_MIME.
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "video/mp4",
            "application/pdf",
        ]
    )
    # Broadcasts attach one video/GIF/document alongside the photo case
    # above; those files run much larger than a product thumbnail, hence
    # the separate, higher cap instead of raising the shared image cap.
    broadcast_media_max_upload_bytes: int = Field(default=20 * 1024 * 1024)  # 20 MB

    # --- inventory ---
    inventory_enc_key: str = Field(
        default="",
        description=(
            "32-byte symmetric key for libsodium SecretBox encryption of voucher "
            "codes at rest. Provide as base64 (urlsafe or standard). In dev a "
            "default-derived key is used when empty; refuses to start in prod."
        ),
    )

    # --- integrations: G2Bulk (G2B) ---
    # Single-account credentials live in env; multi-tenant migration to a
    # supplier_credentials table is a future sprint. Empty ``g2b_api_key``
    # means the adapter reports ``available=False`` and the admin UI shows a
    # "not configured" banner instead of failing health checks.
    g2b_api_key: str = Field(default="")
    g2b_base_url: str = Field(default="https://api.g2bulk.com/v1")
    g2b_webhook_secret: str = Field(
        default="",
        description=(
            "Random token embedded into the webhook URL path. G2B does not "
            "sign callbacks, so the secret in the URL is our only auth layer; "
            "we additionally re-verify the order via /games/order/status "
            "before mutating state."
        ),
    )
    g2b_callback_url: str = Field(
        default="",
        description=(
            "Public URL we pass as ``callback_url`` when creating game orders. "
            "Leave empty in environments where G2B can't reach us — the "
            "polling actor will handle status updates instead."
        ),
    )
    g2b_request_timeout_seconds: float = Field(default=20.0)

    # Waxpeer — Steam wallet top-ups. Empty key disables the supplier the same
    # way an empty g2b key does.
    waxpeer_api_key: str = Field(default="")
    waxpeer_base_url: str = Field(default="https://api.waxpeer.com/v1")
    waxpeer_request_timeout_seconds: float = Field(default=20.0)
    # Waxpeer's cut of a top-up. 0 today; a non-zero value makes us gross the
    # amount up so the customer still receives what they asked for.
    waxpeer_fee_rate: Decimal = Field(default=Decimal("0"), ge=0, lt=1)

    # G-Engine — second source for game top-ups (and Steam in USD/RUB/KZT/UAH).
    # Same empty-key-disables rule as the two above. Its ``limit`` query param
    # is capped at 100 server-side, which the client mirrors rather than
    # discovering through a 422.
    gengine_api_key: str = Field(default="")
    gengine_base_url: str = Field(default="https://api.g-engine.net/v2.1")
    gengine_request_timeout_seconds: float = Field(default=20.0)

    # --- Steam Gifts ---
    # Region-priced Steam gift packages, fulfilled through the G-Engine gifts
    # endpoints (see ``integrations.adapters.gengine``). ``steam_gifts_enabled``
    # is the feature flag the public/miniapp routers (Task 3) gate on;
    # ``steam_gifts_margin_percent`` only seeds ``steam_gift_settings`` row 1
    # on first read — after that, the DB (and its Redis cache) is the source of
    # truth and this env value is never consulted again. See
    # ``yupay.modules.gifts.settings.load_margin_percent``.
    steam_gifts_enabled: bool = Field(default=False)
    steam_gifts_margin_percent: Decimal = Field(default=Decimal("10"))
    # 2026-09-03: this is a buyer-facing COUNTRY code, not a zone label —
    # the "region v2" country picker (``gifts.service.zone_for_country``)
    # resolves it to the zone it prices from. "UZ" is our home market;
    # prod's `secrets/api.env` carries no override for this var, so this
    # code default is what ships on the next deploy.
    steam_gifts_region_default: str = Field(default="UZ")
    steam_gifts_regions: str = Field(default="CIS,RU,KZ,UA")

    # --- acquirer: Octo (octo.uz) ---
    # Hosted-page card acquirer for the UZ market (Uzcard/Humo/Visa). Empty
    # credentials → the gateway reports ``available=False`` and disappears from
    # ``GET /payments/providers`` (the miniapp "Карта" method auto-disables).
    octo_shop_id: str = Field(
        default="",
        description="Octo merchant id (octo_shop_id). Octo types it as Long; we send it as-is.",
    )
    octo_secret: str = Field(default="", description="Octo merchant secret (octo_secret).")
    octo_signature_key: str = Field(
        default="",
        description=(
            "Webhook signature key (Octo's ``unique_key``), issued separately by "
            "Octo tech support. Used to verify SHA1(unique_key + uuid + status). "
            "In prod an empty value means inbound webhooks are rejected — we never "
            "trust an unsigned callback."
        ),
    )
    octo_base_url: str = Field(default="https://secure.octo.uz")
    # Sends ``test: true`` on prepare_payment so Octo treats the charge as a test
    # transaction. Default off; flip to true in dev/.env.
    octo_test_mode: bool = Field(default=False)
    octo_request_timeout_seconds: float = Field(default=20.0)

    # --- acquirer: Paynet (UWS + app deep link) ---
    # We are Paynet's JSON-RPC server: they call /payments/paynet/uws with
    # these Basic credentials. Empty either half → the gateway reports
    # available=False and the endpoint refuses every call with HTTP 401.
    # Not a secret — Paynet knows it, it is in the contract annex. Defaulted
    # so only the password has to be set, and deliberately not "paynet":
    # a guessable username costs nothing to avoid.
    paynet_username: str = Field(default="yupay_paynet")
    paynet_password: str = Field(default="")
    #: Our service identifier in Paynet's registry. Contractual — it is the
    #: number in «Порядок технического взаимодействия» Table 3, and every
    #: inbound call carrying a different one is refused with code 305. Not a
    #: secret either, but not sequential on purpose: 305 is the cheapest
    #: possible answer, so a prober guessing service ids never reaches an
    #: order lookup. The password is still the control; this is depth.
    paynet_service_id: int = Field(default=5878)
    #: The deep link that opens the Paynet app with the order pre-filled.
    #: A format string, NOT a fixed URL: Paynet supplies the exact host and
    #: parameter names after integration, and the published third-party notes
    #: disagree on both. Placeholders: {service_id}, {account} (our order id),
    #: {amount} (tiyin) and {amount_major} (soʻm) — the template picks the
    #: unit. Correcting the format is an env edit and a restart.
    paynet_pay_url_template: str = Field(
        default="https://paynet.uz/payment?provider_id={service_id}&amount={amount}&account={account}"
    )

    # --- acquirer: Payme (Paycom) Merchant API ---
    payme_merchant_id: str = Field(default="")
    payme_key: str = Field(default="")  # production/cabinet key
    payme_test_key: str = Field(default="")  # sandbox key
    payme_login: str = Field(default="Paycom")  # Basic-auth username (convention)
    payme_checkout_url: str = Field(default="https://checkout.paycom.uz")

    # --- acquirer: Uzum (Merchant API) ---
    uzum_service_id: int | None = Field(default=None)
    uzum_login: str = Field(default="")  # production/cabinet login
    uzum_password: str = Field(default="")  # production/cabinet password
    uzum_test_login: str = Field(default="")  # sandbox login
    uzum_test_password: str = Field(default="")  # sandbox password
    uzum_open_service_url: str = Field(default="https://uzumbank.uz/open-service")

    @field_validator("uzum_service_id", mode="before")
    @classmethod
    def _blank_uzum_service_id_to_none(cls, v: object) -> object:
        """Treat an empty/whitespace-only ``UZUM_SERVICE_ID`` as "not set".

        ``uzum_service_id`` is ``int | None`` — the first ``int``-typed acquirer
        env field in this file (Payme's equivalents are all ``str``). Pydantic
        has no built-in "" -> None coercion for numeric fields, so the
        documented "leave empty to disable" convention (see the acquirer's
        ``.env`` comment) would otherwise raise a ``ValidationError`` at
        startup. ``v`` is typed ``object`` (not ``Any``) since a "before"
        validator receives the raw, not-yet-coerced input. Real integers,
        numeric strings, and ``None`` pass through untouched so pydantic can
        still coerce them normally.
        """
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # --- acquirer: Click (Shop API: Prepare/Complete) ---
    # Two Click services share one merchant: web (yupay.uz) and bot (Telegram
    # mini app). Each service has its own SECRET_KEY; Click signs every
    # Prepare/Complete webhook with an MD5 sign_string keyed on that secret, so
    # the incoming ``service_id`` selects which secret verifies the request.
    # ``amount`` is in soums (major units, float), not tiyin.
    click_merchant_id: int | None = Field(default=None)  # shared across both services
    click_service_id_web: int | None = Field(default=None)  # yupay.uz service
    click_service_id_bot: int | None = Field(default=None)  # Telegram mini-app service
    click_secret_key_web: str = Field(default="")  # SECRET_KEY for the web service
    click_secret_key_bot: str = Field(default="")  # SECRET_KEY for the bot service
    click_merchant_user_id_web: int | None = Field(default=None)
    click_merchant_user_id_bot: int | None = Field(default=None)
    click_pay_url: str = Field(default="https://my.click.uz/services/pay")

    @field_validator(
        "click_merchant_id",
        "click_service_id_web",
        "click_service_id_bot",
        "click_merchant_user_id_web",
        "click_merchant_user_id_bot",
        mode="before",
    )
    @classmethod
    def _blank_click_int_to_none(cls, v: object) -> object:
        """Treat an empty/whitespace-only Click numeric env var as "not set".

        Same ``"" -> None`` coercion as :meth:`_blank_uzum_service_id_to_none`,
        applied to every ``int | None`` Click field so the documented "leave
        empty to disable" convention doesn't raise a ``ValidationError`` at
        startup. ``v`` is ``object`` (raw pre-coercion input); real integers,
        numeric strings, and ``None`` pass through untouched.
        """
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # --- admin alerts (separate Telegram bot — NOT the customer bot) ---
    # Dedicated bot so an outage of one channel doesn't drag the other
    # down, and so the customer bot's token doesn't carry admin-chat
    # write rights. Configure both as empty in dev — alerts then no-op.
    tg_alert_bot_token: str = Field(default="")
    tg_alert_chat_id: str = Field(default="")
    # Threshold in percent (absolute) above which a supplier-price move
    # triggers a Telegram alert. Default 5% — anything smaller is noise
    # for ops.
    price_alert_threshold_pct: float = Field(default=5.0)
    # How often the scheduler re-prices every active mapping.
    price_refresh_interval_minutes: int = Field(default=60)
    # Send an ops alert when the supplier's USDT wallet falls below this
    # value (USD-equivalent). Set to 0 to disable.
    supplier_low_balance_threshold: float = Field(default=50.0)

    # --- blog import (Bunzy) ---
    # A third party writes one article a day and we pull it in as a
    # **draft** — never published automatically (ADR-0077). Leave the key
    # empty to disable the job entirely; that is the dev and CI default.
    bunzy_api_url: str = Field(
        default="https://app.bunzy.io",
        description="Origin of the Bunzy blog API; no trailing slash.",
    )
    bunzy_api_key: str = Field(
        default="",
        description=(
            "Server-side only. It authenticates as our whole blog account, so "
            "it must never reach a browser bundle or a client-rendered page."
        ),
    )
    bunzy_import_interval_minutes: int = Field(default=60)
    #: How many of the newest articles each pass looks at.
    bunzy_import_page_size: int = Field(default=20)

    @property
    def is_prod(self) -> bool:
        """Whether we are running in production."""
        return self.environment == "prod"

    @property
    def is_test(self) -> bool:
        """Whether we are running under pytest."""
        return self.environment == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings.

    Re-reading env on every call is wasteful and inconsistent under hot-reload; we cache.
    Tests that need fresh settings should call :pyfunc:`get_settings.cache_clear`.
    """
    return Settings()
