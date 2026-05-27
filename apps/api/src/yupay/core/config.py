"""Application configuration.

Reads from environment variables (and from ``.env`` files in development) via
``pydantic-settings``. The settings object is cached for the process lifetime via
``functools.lru_cache``.
"""

from __future__ import annotations

import base64
import binascii
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

    # --- data ---
    database_url: str = Field(
        default="postgresql+asyncpg://yupay_app:yupay_app@localhost:5432/yupay",
        description="Async SQLAlchemy URL (postgresql+asyncpg://...)",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- broker ---
    dramatiq_broker_url: str = Field(default="redis://localhost:6379/1")

    # --- auth ---
    jwt_public_key: str = Field(default="")
    jwt_private_key: str = Field(default="")
    jwt_kid: str = Field(default="v1", description="JWT key id (kid header)")
    jwt_issuer: str = Field(default="yupay")
    jwt_access_ttl_seconds: int = Field(default=900)  # 15 min
    jwt_refresh_ttl_seconds: int = Field(default=60 * 60 * 24 * 30)  # 30 days
    jwt_guest_ttl_seconds: int = Field(default=60 * 30)  # 30 min for guest checkout
    jwt_ws_ttl_seconds: int = Field(default=60)  # 60 s for WS handshake
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
    fx_crypto_url: str = Field(default="https://api.coingecko.com/api/v3/simple/price")
    fx_cache_fresh_seconds: int = Field(default=15 * 60)
    fx_cache_stale_seconds: int = Field(default=24 * 60 * 60)
    fx_provider_timeout_seconds: float = Field(default=1.5)
    fx_snapshot_max_age_seconds: int = Field(default=5 * 60)

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
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/svg+xml",
        ]
    )

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
