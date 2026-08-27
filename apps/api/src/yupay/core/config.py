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

    # --- broker ---
    dramatiq_broker_url: str = Field(default="redis://localhost:6379/1")

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

    # --- Manual review of large orders (ADR-0047) ---
    manual_review_threshold_usd: Decimal = Field(
        default=Decimal("40"),
        description=(
            "Orders at or above this amount are held after payment instead of being "
            "fulfilled automatically. Denominated in USD because `orders.total_usd` is "
            "stable while the som amount moves with the rate. Default 40 ≈ 550 000 UZS: "
            "the median order is about $1 and the 90th percentile about $11, so this "
            "catches outliers without touching ordinary traffic. Set to 0 to disable."
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

    # --- observability ---
    sentry_dsn: str | None = Field(default=None)
    sentry_traces_sample_rate: float = Field(default=0.1)
    otlp_endpoint: str | None = Field(default=None)
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

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
    uzum_open_service_url: str = Field(default="https://www.uzumbank.uz/open-service")

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
