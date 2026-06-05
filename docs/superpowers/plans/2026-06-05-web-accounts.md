# Web Accounts, Order History & Tracking (+ Email Channel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the public web storefront real accounts — Telegram Login Widget **and** email/password — plus an account area with order history and a live order-status page, backed by a minimal Resend email channel for verification and password reset.

**Architecture:** Backend extends the existing `auth` module with argon2id email/password flows (register/login/verify/forgot/reset) reusing the current session/JWT machinery, and adds a Resend email channel under `notifications`. Verification/reset use short-TTL signed JWTs (`email_verify`/`password_reset`) with a one-time Redis marker for reset. The web client mirrors `apps/miniapp`'s localStorage + refresh-rotation token model in a new browser-side module (the existing `lib/api.ts` server fetcher is untouched), adds an `AuthProvider` + TanStack Query provider, auth/account/order pages, and a polling order-status page that also serves guests via the email link.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, argon2-cffi, httpx, Redis; Next.js 15 App Router, TypeScript strict, TanStack Query v5, react-hook-form + zod, next-intl v4.

**Branch:** `main` (per user instruction). Frequent commits; each task is its own commit(s).

---

## File Structure

**Backend (`apps/api`):**
- `pyproject.toml` — add `argon2-cffi`.
- `src/yupay/core/config.py` — `resend_api_key`, `email_from`, `email_from_name`, `auth_ip_guard_*`.
- `src/yupay/modules/auth/security.py` — `hash_password` / `verify_password` (argon2id).
- `src/yupay/modules/auth/jwt.py` — `email_verify` / `password_reset` kinds + minters.
- `src/yupay/modules/auth/service.py` — `register_user`, `login_password`, `verify_email`, `request_password_reset`, `reset_password`.
- `src/yupay/modules/auth/schemas.py` — request/response models for the new endpoints.
- `src/yupay/modules/auth/routes.py` — the new endpoints (thin) + Redis IP guard.
- `src/yupay/modules/auth/ip_guard.py` — Redis per-IP counter helper.
- `src/yupay/modules/notifications/channels/email.py` — Resend client.
- `src/yupay/modules/notifications/templates.py` — text/html builders for the 4 emails.
- `src/yupay/modules/notifications/service.py` — wire order emails next to the Telegram branch.
- `migrations/versions/0017_user_passwords.py` — schema changes.
- Tests under `tests/unit/`, `tests/integration/`, `tests/contract/`.

**Frontend (`apps/web`):**
- `src/lib/client.ts` — browser fetch + localStorage tokens + refresh (NEW; do not touch `lib/api.ts`).
- `src/lib/auth.tsx` — `AuthProvider`, `useAuth`, `useMe`.
- `src/app/[locale]/Providers.tsx` — `QueryClientProvider` + `AuthProvider` (client).
- `src/app/[locale]/{login,register}/page.tsx`, `src/app/[locale]/auth/{forgot,reset,verify}/page.tsx`.
- `src/app/[locale]/account/page.tsx`, `src/app/[locale]/account/orders/page.tsx`.
- `src/app/[locale]/orders/[orderId]/page.tsx` + `src/components/order/OrderStatus.tsx`.
- `src/components/auth/{AuthForm,TelegramLoginButton,AccountMenu}.tsx`.
- `src/components/Header.tsx` — auth state.
- `src/components/store/PurchasePanel.tsx` — user-owned orders + route to status.
- `packages/i18n/locales/{ru,en,uz}/web.json` — new keys.

**Docs:** `docs/decisions/0026-web-password-auth.md`, `docs/decisions/0027-resend-email-channel.md`, `docs/architecture/{module-map.md,cache-keys.md}`, `docs/architecture/sequence-diagrams/web-auth.mmd`, `docs/architecture/sequence-diagrams/web-order-tracking.mmd`.

---

## Phase 1 — Backend foundations

### Task 1: Config fields + argon2 dependency

**Files:**
- Modify: `apps/api/pyproject.toml` (dependencies)
- Modify: `apps/api/src/yupay/core/config.py` (after `telegram_bot_token`, ~line 99)

- [ ] **Step 1: Add the dependency**

In `apps/api/pyproject.toml`, inside the top-level `dependencies = [ ... ]` array, add (keep alphabetical-ish near other libs):

```toml
    "argon2-cffi>=23.1",
```

- [ ] **Step 2: Add settings**

In `apps/api/src/yupay/core/config.py`, after the `telegram_bot_token` field, add:

```python
    # --- Email (Resend) ---
    resend_api_key: str = Field(default="")
    email_from: str = Field(default="noreply@yupay.uz")
    email_from_name: str = Field(default="YuPay")

    # --- Auth IP guard (lightweight; full rate limiting is a separate concern) ---
    auth_ip_guard_max: int = Field(default=10, description="Max sensitive auth hits per window per IP.")
    auth_ip_guard_window_seconds: int = Field(default=60)
```

- [ ] **Step 3: Sync and verify import**

Run: `cd apps/api && uv sync && uv run python -c "import argon2; from yupay.core.config import get_settings; print('ok', get_settings().email_from)"`
Expected: `ok noreply@yupay.uz`

- [ ] **Step 4: Commit**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/src/yupay/core/config.py
git commit -m "build(api): argon2-cffi dep + Resend/auth-guard settings"
```

---

### Task 2: argon2 password hashing helpers

**Files:**
- Modify: `apps/api/src/yupay/modules/auth/security.py`
- Test: `apps/api/tests/unit/test_auth_security_password.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/unit/test_auth_security_password.py`:

```python
"""Unit tests for argon2id password hashing helpers."""

from __future__ import annotations

from yupay.modules.auth.security import hash_password, verify_password


def test_hash_is_argon2id_and_verifies() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("s3cret-pass")
    assert verify_password("nope", h) is False


def test_hashes_are_salted_and_unique() -> None:
    assert hash_password("same") != hash_password("same")


def test_verify_handles_garbage_hash() -> None:
    assert verify_password("x", "not-a-hash") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/unit/test_auth_security_password.py -q`
Expected: FAIL with `ImportError: cannot import name 'hash_password'`

- [ ] **Step 3: Implement the helpers**

Append to `apps/api/src/yupay/modules/auth/security.py`:

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_password_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash a plaintext password with argon2id.

    Args:
        plain: The user-supplied password.

    Returns:
        An encoded argon2id hash safe to persist (``$argon2id$...``).
    """
    return _password_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time-ish verification of a password against an argon2id hash.

    Returns ``False`` on any mismatch or malformed hash rather than raising, so
    callers can treat the result as a simple boolean.
    """
    try:
        return _password_hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
```

Add the new names to the module's `__all__` if it has one.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/unit/test_auth_security_password.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/auth/security.py apps/api/tests/unit/test_auth_security_password.py
git commit -m "feat(auth): argon2id password hash/verify helpers"
```

---

### Task 3: JWT kinds for email verification + password reset

**Files:**
- Modify: `apps/api/src/yupay/modules/auth/jwt.py`
- Test: `apps/api/tests/unit/test_auth_jwt_email_tokens.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/unit/test_auth_jwt_email_tokens.py`:

```python
"""Email-verify / password-reset JWT minting + verification."""

from __future__ import annotations

import pytest

from yupay.core.errors import UnauthorizedError
from yupay.modules.auth import jwt as authjwt


def test_email_verify_roundtrip() -> None:
    token = authjwt.mint_email_verify(sub="user-1")
    claims = authjwt.verify(token, expected_kind="email_verify")
    assert claims.sub == "user-1"
    assert claims.jti


def test_password_reset_roundtrip_has_jti() -> None:
    token = authjwt.mint_password_reset(sub="user-2")
    claims = authjwt.verify(token, expected_kind="password_reset")
    assert claims.sub == "user-2"
    assert claims.jti


def test_kind_mismatch_rejected() -> None:
    token = authjwt.mint_email_verify(sub="user-3")
    with pytest.raises(UnauthorizedError):
        authjwt.verify(token, expected_kind="password_reset")
```

This test requires a configured JWT keypair. The repo's test fixtures already configure one for the other `auth` JWT tests; reuse the same conftest setup. If `tests/unit/conftest.py` does not already set `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY`, mirror the fixture from the existing `tests/unit/test_auth_jwt*.py` (search: `grep -rl "mint_access" apps/api/tests`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/unit/test_auth_jwt_email_tokens.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'mint_email_verify'`

- [ ] **Step 3: Extend the kinds and add minters**

In `apps/api/src/yupay/modules/auth/jwt.py`:

Change `TokenKind`:

```python
TokenKind = Literal["access", "refresh", "guest", "ws", "email_verify", "password_reset"]
```

Add two TTL-driven minters (after `mint_ws_handshake`):

```python
def mint_email_verify(
    *,
    sub: str,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived token confirming ownership of a user's email."""
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="email_verify",
        ttl_seconds=s.jwt_email_token_ttl_seconds,
        settings=s,
    )
    return _encode(payload, settings=s)


def mint_password_reset(
    *,
    sub: str,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived, single-use (via Redis marker) password-reset token."""
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="password_reset",
        ttl_seconds=s.jwt_email_token_ttl_seconds,
        settings=s,
    )
    return _encode(payload, settings=s)
```

- [ ] **Step 4: Add the TTL setting**

In `apps/api/src/yupay/core/config.py`, next to the other `jwt_*_ttl_seconds`:

```python
    jwt_email_token_ttl_seconds: int = Field(default=60 * 30)  # 30 min for verify/reset links
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/unit/test_auth_jwt_email_tokens.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/auth/jwt.py apps/api/src/yupay/core/config.py apps/api/tests/unit/test_auth_jwt_email_tokens.py
git commit -m "feat(auth): email_verify + password_reset JWT kinds"
```

---

### Task 4: Resend email channel + contract test

**Files:**
- Create: `apps/api/src/yupay/modules/notifications/channels/email.py`
- Test: `apps/api/tests/contract/test_resend_email.py`

- [ ] **Step 1: Write the failing contract test**

Create `apps/api/tests/contract/test_resend_email.py`:

```python
"""Contract test for the Resend email channel (respx-mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from yupay.core.config import get_settings
from yupay.modules.notifications.channels.email import EmailSendError, send_email

RESEND_URL = "https://api.resend.com/emails"


@pytest.fixture(autouse=True)
def _resend_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


@respx.mock
@pytest.mark.asyncio
async def test_send_email_success() -> None:
    route = respx.post(RESEND_URL).mock(
        return_value=httpx.Response(200, json={"id": "msg_123"})
    )
    msg_id = await send_email(
        to="buyer@example.com", subject="Hi", html="<b>Hi</b>", text="Hi"
    )
    assert msg_id == "msg_123"
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer re_test_key"


@respx.mock
@pytest.mark.asyncio
async def test_send_email_raises_on_4xx() -> None:
    respx.post(RESEND_URL).mock(return_value=httpx.Response(422, json={"message": "bad"}))
    with pytest.raises(EmailSendError):
        await send_email(to="x@example.com", subject="s", html="h", text="t")


@respx.mock
@pytest.mark.asyncio
async def test_send_email_raises_on_429() -> None:
    respx.post(RESEND_URL).mock(return_value=httpx.Response(429, json={"message": "rate"}))
    with pytest.raises(EmailSendError):
        await send_email(to="x@example.com", subject="s", html="h", text="t")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/contract/test_resend_email.py -q`
Expected: FAIL with `ModuleNotFoundError: ... channels.email`

- [ ] **Step 3: Implement the channel**

Create `apps/api/src/yupay/modules/notifications/channels/email.py`:

```python
"""Transactional email via Resend (https://resend.com).

A thin async wrapper over the Resend REST API. Only the ``send`` capability is
used; the client is created per call (cheap) so configuration changes are picked
up without a process restart. PII (the recipient address) is never logged.
"""

from __future__ import annotations

import httpx

from yupay.core.config import get_settings

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = httpx.Timeout(10.0)


class EmailSendError(RuntimeError):
    """Raised when Resend rejects a send (non-2xx) or the call cannot complete."""


async def send_email(*, to: str, subject: str, html: str, text: str) -> str:
    """Send one transactional email through Resend.

    Args:
        to: Recipient address.
        subject: Subject line.
        html: HTML body.
        text: Plain-text fallback body.

    Returns:
        The Resend message id.

    Raises:
        EmailSendError: When the API key is missing or Resend returns non-2xx.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailSendError("RESEND_API_KEY is not configured")

    payload = {
        "from": f"{settings.email_from_name} <{settings.email_from}>",
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    headers = {"Authorization": f"Bearer {settings.resend_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_RESEND_URL, json=payload, headers=headers)
    except httpx.HTTPError as exc:  # network/timeout
        raise EmailSendError("resend request failed") from exc

    if resp.status_code >= 300:
        raise EmailSendError(f"resend returned {resp.status_code}")
    return str(resp.json().get("id", ""))


__all__ = ["EmailSendError", "send_email"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/contract/test_resend_email.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/notifications/channels/email.py apps/api/tests/contract/test_resend_email.py
git commit -m "feat(notifications): Resend email channel"
```

---

### Task 5: Email template builders

**Files:**
- Create: `apps/api/src/yupay/modules/notifications/templates.py`
- Test: `apps/api/tests/unit/test_email_templates.py`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/unit/test_email_templates.py`:

```python
"""Email template builders return matching subject/html/text."""

from __future__ import annotations

from yupay.modules.notifications.templates import (
    order_confirmation_email,
    order_delivered_email,
    password_reset_email,
    verify_email_email,
)


def test_verify_email_contains_link() -> None:
    t = verify_email_email(link="https://yupay.uz/ru/auth/verify?token=abc")
    assert "abc" in t.html and "abc" in t.text
    assert t.subject


def test_password_reset_contains_link() -> None:
    t = password_reset_email(link="https://yupay.uz/ru/auth/reset?token=xyz")
    assert "xyz" in t.html and "xyz" in t.text


def test_order_confirmation_has_order_id() -> None:
    t = order_confirmation_email(order_id="abcdef12", link="https://yupay.uz/ru/orders/abcdef12")
    assert "abcdef12" in t.html


def test_order_delivered_has_link() -> None:
    t = order_delivered_email(order_id="abcdef12", link="https://yupay.uz/ru/orders/abcdef12")
    assert "abcdef12" in t.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/unit/test_email_templates.py -q`
Expected: FAIL with import error.

- [ ] **Step 3: Implement the builders**

Create `apps/api/src/yupay/modules/notifications/templates.py`:

```python
"""Plain, dependency-free email template builders.

Each returns an :class:`EmailContent` (subject + html + text). Copy is in
Russian (the storefront's default locale); per-locale copy can be layered later.
Keep these simple — no templating engine, just f-strings — so they are trivial
to unit-test and review.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EmailContent(BaseModel):
    """Rendered email: subject + html + plain-text bodies."""

    model_config = ConfigDict(frozen=True)

    subject: str
    html: str
    text: str


def _wrap(body_html: str) -> str:
    return (
        '<div style="font-family:system-ui,sans-serif;max-width:480px;margin:auto">'
        f"{body_html}"
        '<p style="color:#888;font-size:12px;margin-top:24px">YuPay</p></div>'
    )


def verify_email_email(*, link: str) -> EmailContent:
    """Email-verification message with a confirmation link."""
    return EmailContent(
        subject="Подтвердите ваш email — YuPay",
        html=_wrap(
            "<h2>Подтверждение email</h2>"
            "<p>Нажмите кнопку, чтобы подтвердить ваш адрес:</p>"
            f'<p><a href="{link}">Подтвердить email</a></p>'
            f"<p>Или откройте ссылку: {link}</p>"
        ),
        text=f"Подтвердите ваш email, открыв ссылку: {link}",
    )


def password_reset_email(*, link: str) -> EmailContent:
    """Password-reset message with a reset link."""
    return EmailContent(
        subject="Сброс пароля — YuPay",
        html=_wrap(
            "<h2>Сброс пароля</h2>"
            "<p>Вы запросили сброс пароля. Ссылка действует 30 минут:</p>"
            f'<p><a href="{link}">Задать новый пароль</a></p>'
            f"<p>Или откройте: {link}</p>"
            "<p>Если это были не вы — проигнорируйте письмо.</p>"
        ),
        text=f"Сброс пароля (ссылка действует 30 минут): {link}",
    )


def order_confirmation_email(*, order_id: str, link: str) -> EmailContent:
    """Order-created confirmation for guest buyers."""
    short = order_id[:8]
    return EmailContent(
        subject=f"Заказ #{short} принят — YuPay",
        html=_wrap(
            "<h2>Спасибо за заказ!</h2>"
            f"<p>Заказ <b>#{short}</b> принят. Отслеживайте статус по ссылке:</p>"
            f'<p><a href="{link}">Открыть заказ</a></p>'
        ),
        text=f"Заказ #{short} принят. Статус: {link}",
    )


def order_delivered_email(*, order_id: str, link: str) -> EmailContent:
    """Order-delivered notification for guest buyers."""
    short = order_id[:8]
    return EmailContent(
        subject=f"Заказ #{short} выполнен — YuPay",
        html=_wrap(
            "<h2>Ваш заказ выполнен</h2>"
            f"<p>Заказ <b>#{short}</b> доставлен. Откройте, чтобы увидеть артефакт:</p>"
            f'<p><a href="{link}">Открыть заказ</a></p>'
        ),
        text=f"Заказ #{short} выполнен. Откройте: {link}",
    )


__all__ = [
    "EmailContent",
    "order_confirmation_email",
    "order_delivered_email",
    "password_reset_email",
    "verify_email_email",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/unit/test_email_templates.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/notifications/templates.py apps/api/tests/unit/test_email_templates.py
git commit -m "feat(notifications): transactional email templates"
```

---

## Phase 2 — Backend auth flows

### Task 6: Migration — password_hash, email_verified_at, unique email index

**Files:**
- Create: `apps/api/migrations/versions/0017_user_passwords.py`

> Confirm the latest revision id first: `ls apps/api/migrations/versions | sort | tail -1` and open it to read its `revision = "..."`. Use that value as `down_revision` below (shown as `<PREV_REVISION>`).

- [ ] **Step 1: Write the migration**

Create `apps/api/migrations/versions/0017_user_passwords.py`:

```python
"""Add password_hash + email_verified_at to users; unique live-email index.

Revision ID: 0017_user_passwords
Revises: <PREV_REVISION>
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_user_passwords"
down_revision = "<PREV_REVISION>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # One live account per email. Guests do not create user rows, so existing
    # data cannot violate this. Partial unique on lower(email) for non-deleted rows.
    op.execute(
        "CREATE UNIQUE INDEX uq_users_email_live "
        "ON users (lower(email)) WHERE email IS NOT NULL AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_email_live")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")
```

- [ ] **Step 2: Add the ORM columns**

In `apps/api/src/yupay/modules/users/models.py`, in the `User` class after `email`:

```python
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

(`DateTime` and `datetime` are already imported in that file.)

- [ ] **Step 3: Apply and verify**

Run: `make migrate` (or `cd apps/api && uv run alembic upgrade head`)
Then: `docker compose -p yupay-dev exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d users"'`
Expected: `password_hash`, `email_verified_at` columns and `uq_users_email_live` index present.

- [ ] **Step 4: Commit**

```bash
git add apps/api/migrations/versions/0017_user_passwords.py apps/api/src/yupay/modules/users/models.py
git commit -m "feat(users): password_hash + email_verified_at + unique live-email index"
```

---

### Task 7: Register flow (service + schema + route)

**Files:**
- Modify: `apps/api/src/yupay/modules/auth/service.py`
- Modify: `apps/api/src/yupay/modules/auth/schemas.py`
- Modify: `apps/api/src/yupay/modules/auth/routes.py`
- Test: `apps/api/tests/integration/test_auth_password.py`

> Tasks 7-11 share one integration test file. Each task appends its test(s). Use the repo's existing integration client/fixtures (mirror `tests/integration/test_g2b_import.py` for the `integration_client` + DB session fixtures).

- [ ] **Step 1: Write the failing test (register)**

Create `apps/api/tests/integration/test_auth_password.py`:

```python
"""Email/password auth flows: register, login, verify, forgot, reset."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_register_creates_user_and_returns_tokens(integration_client) -> None:
    r = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "newbie@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]

    me = await integration_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "newbie@example.com"


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(integration_client) -> None:
    payload = {"email": "dupe@example.com", "password": "hunter2hunter2"}
    first = await integration_client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await integration_client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -q`
Expected: FAIL (404 — route missing).

- [ ] **Step 3: Add the schemas**

In `apps/api/src/yupay/modules/auth/schemas.py`:

```python
class RegisterIn(BaseModel):
    """Body of ``POST /auth/register``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    locale: str = Field(default="ru", max_length=8)


class LoginIn(BaseModel):
    """Body of ``POST /auth/login``."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=10, max_length=2048)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=2048)
    new_password: str = Field(min_length=8, max_length=200)
```

Add the new names to `__all__`.

- [ ] **Step 4: Add the service function**

In `apps/api/src/yupay/modules/auth/service.py` add imports and `register_user`:

```python
from sqlalchemy.exc import IntegrityError

from yupay.core.errors import ConflictError, ValidationError
from yupay.modules.auth.security import hash_password, verify_password
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import (
    password_reset_email,
    verify_email_email,
)
```

```python
async def register_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    locale: str = "ru",
    settings: Settings | None = None,
    verify_link_base: str | None = None,
) -> SessionTokens:
    """Create an email/password user, open a session, and send a verify email.

    Args:
        db: Async session.
        email: New account email (uniqueness enforced by a partial index).
        password: Plaintext password (hashed with argon2id).
        locale: Preferred locale for the account.
        settings: Optional settings override.
        verify_link_base: Absolute URL prefix for the verification link, e.g.
            ``https://yupay.uz/ru``. When ``None`` no email is sent (dev).

    Returns:
        Freshly minted session tokens for immediate login.

    Raises:
        ConflictError: When the email already belongs to a live account.
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    user = User(
        id=new_id(),
        email=normalised,
        locale=locale,
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("email already registered") from exc

    if verify_link_base:
        token = authjwt.mint_email_verify(sub=user.id, settings=s)
        link = f"{verify_link_base.rstrip('/')}/auth/verify?token={token}"
        content = verify_email_email(link=link)
        try:
            await send_email(
                to=normalised,
                subject=content.subject,
                html=content.html,
                text=content.text,
            )
        except EmailSendError:
            pass  # non-blocking: account is usable; user can re-request verification

    return await _open_session(db, user=user, settings=s)
```

> If `ConflictError` does not exist in `yupay.core.errors`, use the project's existing conflict/409 error class (grep `core/errors.py`); adjust the import and the route handler accordingly.

- [ ] **Step 5: Add the route**

In `apps/api/src/yupay/modules/auth/routes.py` (import the new schemas + helper to read the locale-aware base URL):

```python
def _web_base(request: Request, locale: str) -> str:
    """Best-effort absolute web base for links in emails (e.g. https://host/ru)."""
    settings = get_settings()
    base = settings.web_base_url or str(request.base_url).rstrip("/")
    return f"{base.rstrip('/')}/{locale}"


@router.post(
    "/register",
    response_model=TokensOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register an email/password account",
)
async def register_route(
    body: RegisterIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    tokens = await svc.register_user(
        db,
        email=body.email,
        password=body.password,
        locale=body.locale,
        verify_link_base=_web_base(request, body.locale),
    )
    return _tokens_response(tokens)
```

Add a `web_base_url: str = Field(default="")` setting in `config.py`. Ensure `status`, `Request` are imported in `routes.py` (mirror existing imports).

- [ ] **Step 6: Run to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/auth/ apps/api/src/yupay/core/config.py apps/api/tests/integration/test_auth_password.py
git commit -m "feat(auth): email/password registration"
```

---

### Task 8: Login flow

**Files:**
- Modify: `apps/api/src/yupay/modules/auth/service.py`, `routes.py`
- Test: append to `apps/api/tests/integration/test_auth_password.py`

- [ ] **Step 1: Append the failing tests**

```python
@pytest.mark.asyncio
async def test_login_succeeds_with_correct_password(integration_client) -> None:
    await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "loginok@example.com", "password": "hunter2hunter2"},
    )
    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "loginok@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(integration_client) -> None:
    await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "loginbad@example.com", "password": "hunter2hunter2"},
    )
    r = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "loginbad@example.com", "password": "WRONGWRONG"},
    )
    assert r.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -k login -q`
Expected: FAIL (404).

- [ ] **Step 3: Add the service function**

In `service.py`:

```python
async def login_password(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings | None = None,
) -> SessionTokens:
    """Authenticate an email/password user and open a session.

    Raises:
        UnauthorizedError: On unknown email, Telegram-only account (no password),
            or wrong password — all surfaced identically to avoid enumeration.
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    stmt = select(User).where(
        sa.func.lower(User.email) == normalised,
        User.deleted_at.is_(None),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise UnauthorizedError("invalid email or password")
    return await _open_session(db, user=user, settings=s)
```

Add `import sqlalchemy as sa` if not present.

- [ ] **Step 4: Add the route**

```python
@router.post(
    "/login",
    response_model=TokensOut,
    summary="Log in with email + password",
)
async def login_route(
    body: LoginIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    await guard_ip(request, bucket="login")  # added in Task 11; safe no-op until then
    tokens = await svc.login_password(db, email=body.email, password=body.password)
    return _tokens_response(tokens)
```

> If Task 11 is not yet implemented, omit the `guard_ip` line and add it in Task 11.

- [ ] **Step 5: Run to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -k login -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/auth/
git commit -m "feat(auth): email/password login"
```

---

### Task 9: Verify-email flow

**Files:**
- Modify: `service.py`, `routes.py`
- Test: append to `test_auth_password.py`

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.asyncio
async def test_verify_email_marks_verified(integration_client, db_session) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "verify@example.com", "password": "hunter2hunter2"},
    )
    access = reg.json()["access_token"]
    # Mint a verify token directly (the email send is a no-op in tests).
    from yupay.modules.auth import jwt as authjwt
    from yupay.modules.auth.service import current_user

    user = await current_user(db_session, access)
    token = authjwt.mint_email_verify(sub=user.id)

    r = await integration_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 204, r.text

    me = await integration_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    # MeOut may not expose email_verified_at; assert via a fresh DB read instead.
    await db_session.refresh(user)
    assert user.email_verified_at is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -k verify_email -q`
Expected: FAIL (404).

- [ ] **Step 3: Add the service function**

```python
async def verify_email(
    db: AsyncSession,
    *,
    token: str,
    settings: Settings | None = None,
) -> None:
    """Mark a user's email as verified from a signed ``email_verify`` token."""
    s = settings or get_settings()
    claims = authjwt.verify(token, expected_kind="email_verify", settings=s)
    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise NotFoundError("user not found")
    if user.email_verified_at is None:
        user.email_verified_at = now()
        await db.flush()
```

- [ ] **Step 4: Add the route**

```python
@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm an email address from a signed token",
)
async def verify_email_route(
    body: VerifyEmailIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    await svc.verify_email(db, token=body.token)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -k verify_email -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/auth/
git commit -m "feat(auth): email verification endpoint"
```

---

### Task 10: Forgot + reset password (Redis one-time marker + session revoke)

**Files:**
- Modify: `service.py`, `routes.py`
- Test: append to `test_auth_password.py`

- [ ] **Step 1: Append the failing tests**

```python
@pytest.mark.asyncio
async def test_forgot_is_non_enumerating(integration_client) -> None:
    # Unknown email still returns 204.
    r = await integration_client.post(
        "/api/v1/auth/password/forgot", json={"email": "ghost@example.com"}
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_reset_changes_password_and_revokes_sessions(integration_client, db_session) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "reset@example.com", "password": "oldpassword1"},
    )
    old_refresh = reg.json()["refresh_token"]

    from yupay.modules.auth import jwt as authjwt
    from yupay.modules.auth.service import current_user

    user = await current_user(db_session, reg.json()["access_token"])
    token = authjwt.mint_password_reset(sub=user.id)

    r = await integration_client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "brandnewpass9"},
    )
    assert r.status_code == 204, r.text

    # Old refresh is revoked.
    refreshed = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert refreshed.status_code == 401

    # New password works; old one does not.
    ok = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "brandnewpass9"},
    )
    assert ok.status_code == 200
    bad = await integration_client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "oldpassword1"},
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_reset_token_is_single_use(integration_client, db_session) -> None:
    reg = await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "single@example.com", "password": "oldpassword1"},
    )
    from yupay.modules.auth import jwt as authjwt
    from yupay.modules.auth.service import current_user

    user = await current_user(db_session, reg.json()["access_token"])
    token = authjwt.mint_password_reset(sub=user.id)

    first = await integration_client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "newpass111"}
    )
    assert first.status_code == 204
    second = await integration_client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "newpass222"}
    )
    assert second.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -k "forgot or reset" -q`
Expected: FAIL (404).

- [ ] **Step 3: Add the service functions**

In `service.py` (import Redis accessor: `from yupay.core.redis import get_redis`):

```python
async def request_password_reset(
    db: AsyncSession,
    *,
    email: str,
    settings: Settings | None = None,
    reset_link_base: str | None = None,
) -> None:
    """Send a reset link if the email maps to a password account. Always silent.

    Never reveals whether the email exists (no enumeration): the caller returns
    204 regardless.
    """
    s = settings or get_settings()
    normalised = email.strip().lower()
    stmt = select(User).where(
        sa.func.lower(User.email) == normalised,
        User.deleted_at.is_(None),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.password_hash or not reset_link_base:
        return
    token = authjwt.mint_password_reset(sub=user.id, settings=s)
    link = f"{reset_link_base.rstrip('/')}/auth/reset?token={token}"
    content = password_reset_email(link=link)
    try:
        await send_email(
            to=normalised, subject=content.subject, html=content.html, text=content.text
        )
    except EmailSendError:
        pass


async def reset_password(
    db: AsyncSession,
    *,
    token: str,
    new_password: str,
    settings: Settings | None = None,
) -> None:
    """Consume a single-use reset token, set a new password, revoke sessions.

    Raises:
        UnauthorizedError: On an invalid/expired token or one already consumed.
    """
    s = settings or get_settings()
    claims = authjwt.verify(token, expected_kind="password_reset", settings=s)

    redis = get_redis()
    marker = f"auth:pwreset:{claims.jti}"
    # SET NX returns None when the key already exists → token already used.
    was_set = await redis.set(marker, "1", ex=s.jwt_email_token_ttl_seconds, nx=True)
    if not was_set:
        raise UnauthorizedError("reset token already used")

    user = await get_user_by_id(db, claims.sub)
    if user is None:
        raise NotFoundError("user not found")
    user.password_hash = hash_password(new_password)
    await db.flush()
    await _revoke_all_for_user(db, user.id)
```

- [ ] **Step 4: Add the routes**

```python
@router.post(
    "/password/forgot",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Request a password-reset email (non-enumerating)",
)
async def forgot_route(
    body: ForgotPasswordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    await guard_ip(request, bucket="forgot")  # Task 11
    await svc.request_password_reset(
        db, email=body.email, reset_link_base=_web_base(request, "ru")
    )


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password from a reset token",
)
async def reset_route(
    body: ResetPasswordIn,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> None:
    await svc.reset_password(db, token=body.token, new_password=body.new_password)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py -k "forgot or reset" -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/auth/ apps/api/tests/integration/test_auth_password.py
git commit -m "feat(auth): password forgot/reset with single-use token + session revoke"
```

---

### Task 11: Redis per-IP guard on sensitive endpoints

**Files:**
- Create: `apps/api/src/yupay/modules/auth/ip_guard.py`
- Modify: `apps/api/src/yupay/modules/auth/routes.py` (wire `guard_ip` into login + forgot)
- Test: `apps/api/tests/integration/test_auth_ip_guard.py`

- [ ] **Step 1: Write the failing test**

```python
"""IP guard returns 429 after the configured threshold."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_login_ip_guard_trips(integration_client, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "3")
    from yupay.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    statuses = []
    for _ in range(5):
        r = await integration_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "whatever12"},
        )
        statuses.append(r.status_code)
    assert 429 in statuses
    get_settings.cache_clear()  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_ip_guard.py -q`
Expected: FAIL (no 429 — guard absent).

- [ ] **Step 3: Implement the guard**

Create `apps/api/src/yupay/modules/auth/ip_guard.py`:

```python
"""Lightweight Redis per-IP rate guard for sensitive auth endpoints.

Not a substitute for full edge rate limiting — just blunts brute force and
email bombing on ``login`` / ``password/forgot``. Best-effort: Redis errors fail
open (the endpoint proceeds) so a cache hiccup never locks out auth.
"""

from __future__ import annotations

import contextlib

from fastapi import Request

from yupay.core.config import get_settings
from yupay.core.errors import RateLimitedError
from yupay.core.redis import get_redis


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def guard_ip(request: Request, *, bucket: str) -> None:
    """Increment a per-IP counter; raise ``RateLimitedError`` past the threshold."""
    settings = get_settings()
    ip = _client_ip(request)
    key = f"auth:ipguard:{bucket}:{ip}"
    redis = get_redis()
    count = 0
    with contextlib.suppress(Exception):  # fail open on Redis trouble
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.auth_ip_guard_window_seconds)
    if count > settings.auth_ip_guard_max:
        raise RateLimitedError("too many attempts, slow down")
```

> If `RateLimitedError` (a 429) does not exist in `core/errors.py`, add one mirroring the existing error classes (subclass the base `AppError`/`HTTPException` pattern with `status_code = 429`). Confirm with `grep -n "class .*Error" apps/api/src/yupay/core/errors.py`.

- [ ] **Step 4: Wire into routes**

Add `from yupay.modules.auth.ip_guard import guard_ip` to `routes.py`. Ensure the `guard_ip(...)` calls in `login_route` and `forgot_route` (added in Tasks 8/10) are present.

- [ ] **Step 5: Run to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_ip_guard.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full auth suite**

Run: `cd apps/api && uv run pytest tests/integration/test_auth_password.py tests/integration/test_auth_ip_guard.py tests/unit/test_auth_security_password.py tests/unit/test_auth_jwt_email_tokens.py --cov=yupay.modules.auth --cov-report=term-missing -q`
Expected: PASS; `auth` coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/auth/ apps/api/tests/integration/test_auth_ip_guard.py
git commit -m "feat(auth): Redis per-IP guard on login/forgot"
```

---

### Task 12: Wire guest order emails into the notifications dispatch

**Files:**
- Modify: `apps/api/src/yupay/modules/notifications/service.py`
- Test: `apps/api/tests/integration/test_order_emails.py` (or unit with a send spy)

- [ ] **Step 1: Inspect the existing dispatch**

Read `apps/api/src/yupay/modules/notifications/service.py` to find where order events (placed / delivered) fan out to the Telegram channel. The email branch goes immediately next to it, gated on a guest email.

- [ ] **Step 2: Write the failing test**

Create `apps/api/tests/integration/test_order_emails.py` — spy on `send_email`:

```python
"""Guest order events trigger a transactional email."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_delivered_guest_order_sends_email(monkeypatch) -> None:
    sent: list[dict] = []

    async def _spy(*, to, subject, html, text):  # noqa: ANN001
        sent.append({"to": to, "subject": subject})
        return "msg_test"

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _spy, raising=False
    )

    from yupay.modules.notifications.service import notify_order_delivered

    await notify_order_delivered(
        order_id="abcdef1234",
        guest_email="guest@example.com",
        web_base="https://yupay.uz/ru",
    )
    assert sent and sent[0]["to"] == "guest@example.com"
```

> Match the real dispatch function name/signature discovered in Step 1. If notifications dispatch is event-object-based rather than function-per-event, adapt the test to call the actual entrypoint with a delivered-order event whose `guest_email` is set.

- [ ] **Step 3: Implement the email branch**

In `notifications/service.py`, import and call the email channel for guest orders:

```python
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import (
    order_confirmation_email,
    order_delivered_email,
)
```

Add (or extend) the order-delivered / order-confirmation handlers so that when the order has a `guest_email`, an email is sent best-effort:

```python
async def notify_order_delivered(
    *, order_id: str, guest_email: str | None, web_base: str | None
) -> None:
    """Email a guest buyer that their order is delivered (best-effort)."""
    if not guest_email or not web_base:
        return
    link = f"{web_base.rstrip('/')}/orders/{order_id}"
    content = order_delivered_email(order_id=order_id, link=link)
    try:
        await send_email(
            to=guest_email, subject=content.subject, html=content.html, text=content.text
        )
    except EmailSendError:
        pass
```

Wire `notify_order_delivered` / a matching `notify_order_confirmation` into the existing dispatch next to the Telegram notification, passing the order's `guest_email` and the configured `web_base_url`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_order_emails.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/notifications/service.py apps/api/tests/integration/test_order_emails.py
git commit -m "feat(notifications): email guests on order confirmation/delivery"
```

---

### Task 13: Regenerate OpenAPI + TS client

**Files:**
- Modify: `docs/api/openapi.json`, `packages/api-client/**` (generated)

- [ ] **Step 1: Regenerate**

Run: `make gen-api`

- [ ] **Step 2: Sanity-check the diff**

Run: `git diff --stat docs/api/openapi.json packages/api-client`
Expected: new `/auth/register`, `/auth/login`, `/auth/verify-email`, `/auth/password/forgot`, `/auth/password/reset` paths present.

- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi.json packages/api-client
git commit -m "build(api): regenerate OpenAPI for auth password endpoints"
```

---

## Phase 3 — Frontend (apps/web)

### Task 14: Browser API client + token storage

**Files:**
- Create: `apps/web/src/lib/client.ts`

> Do NOT modify `apps/web/src/lib/api.ts` (server-only catalog fetcher). This is a separate browser module.

- [ ] **Step 1: Implement the client**

Create `apps/web/src/lib/client.ts`:

```typescript
"use client";

/**
 * Browser-side API client for authenticated calls. Mirrors apps/miniapp:
 * access + refresh tokens in localStorage with a single auto-refresh on 401.
 * Server Components must keep using `lib/api.ts` instead.
 */

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

const ACCESS_KEY = "yupay.web.access_token";
const REFRESH_KEY = "yupay.web.refresh_token";

export interface Tokens {
  access_token: string;
  refresh_token?: string | null;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setTokens(access: string, refresh?: string | null): void {
  try {
    window.localStorage.setItem(ACCESS_KEY, access);
    if (refresh) window.localStorage.setItem(REFRESH_KEY, refresh);
  } catch {
    /* storage blocked — ignore */
  }
}

export function clearTokens(): void {
  try {
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public path: string,
  ) {
    super(`API ${String(status)} on ${path}`);
    this.name = "ApiError";
  }
}

async function refreshAccess(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) {
    clearTokens();
    return null;
  }
  const tokens = (await res.json()) as Tokens;
  setTokens(tokens.access_token, tokens.refresh_token ?? null);
  return tokens.access_token;
}

interface ReqOpts {
  method?: string;
  body?: unknown;
  anonymous?: boolean;
  headers?: Record<string, string>;
  retry?: boolean;
}

export async function apiFetch<T>(path: string, opts: ReqOpts = {}): Promise<T> {
  const headers = new Headers(opts.headers);
  if (opts.body !== undefined) headers.set("Content-Type", "application/json");
  const token = getAccessToken();
  if (!opts.anonymous && token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${BASE}/api/v1${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 401 && !opts.anonymous && !opts.retry) {
    const fresh = await refreshAccess();
    if (fresh) return apiFetch<T>(path, { ...opts, retry: true });
  }
  if (!res.ok) throw new ApiError(res.status, path);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/lib/client.ts
git commit -m "feat(web): browser API client with token storage + refresh"
```

---

### Task 15: AuthProvider + QueryClient provider

**Files:**
- Create: `apps/web/src/lib/auth.tsx`
- Create: `apps/web/src/app/[locale]/Providers.tsx`
- Modify: `apps/web/src/app/[locale]/layout.tsx` (wrap children in `<Providers>`)

- [ ] **Step 1: Implement the auth context**

Create `apps/web/src/lib/auth.tsx`:

```tsx
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";

import { apiFetch, clearTokens, getAccessToken, setTokens, type Tokens } from "./client";

export interface Me {
  id: string;
  email: string | null;
  locale: string;
  display_currency: string;
  display_name: string | null;
  photo_url: string | null;
  roles: string[];
}

interface AuthValue {
  user: Me | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, locale: string) => Promise<void>;
  loginWithTelegram: (payload: Record<string, unknown>) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<Me>("/auth/me"),
    enabled: typeof window !== "undefined" && Boolean(getAccessToken()),
    retry: false,
    staleTime: 60_000,
  });

  const afterTokens = useCallback(
    async (tokens: Tokens) => {
      setTokens(tokens.access_token, tokens.refresh_token ?? null);
      await qc.invalidateQueries({ queryKey: ["me"] });
    },
    [qc],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await apiFetch<Tokens>("/auth/login", {
        method: "POST",
        anonymous: true,
        body: { email, password },
      });
      await afterTokens(tokens);
    },
    [afterTokens],
  );

  const register = useCallback(
    async (email: string, password: string, locale: string) => {
      const tokens = await apiFetch<Tokens>("/auth/register", {
        method: "POST",
        anonymous: true,
        body: { email, password, locale },
      });
      await afterTokens(tokens);
    },
    [afterTokens],
  );

  const loginWithTelegram = useCallback(
    async (payload: Record<string, unknown>) => {
      const tokens = await apiFetch<Tokens>("/auth/telegram/widget", {
        method: "POST",
        anonymous: true,
        body: payload,
      });
      await afterTokens(tokens);
    },
    [afterTokens],
  );

  const logout = useCallback(() => {
    clearTokens();
    qc.setQueryData(["me"], null);
    void qc.invalidateQueries({ queryKey: ["me"] });
  }, [qc]);

  const value = useMemo<AuthValue>(
    () => ({
      user: meQuery.data ?? null,
      isLoading: meQuery.isLoading,
      login,
      register,
      loginWithTelegram,
      logout,
    }),
    [meQuery.data, meQuery.isLoading, login, register, loginWithTelegram, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
```

> Confirm the Telegram widget route path is `/auth/telegram/widget` (`grep -n "telegram" apps/api/src/yupay/api/v1/__init__.py` and the auth router prefix). Adjust if the mounted path differs.

- [ ] **Step 2: Implement Providers**

Create `apps/web/src/app/[locale]/Providers.tsx`:

```tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AuthProvider } from "@/lib/auth";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 3: Mount in layout**

In `apps/web/src/app/[locale]/layout.tsx`, wrap the children currently inside `<NextIntlClientProvider>` with `<Providers>`:

```tsx
import { Providers } from "./Providers";
// ...
<NextIntlClientProvider locale={locale} messages={messages}>
  <Providers>
    {/* existing header/children/footer tree */}
  </Providers>
</NextIntlClientProvider>
```

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/auth.tsx apps/web/src/app/[locale]/Providers.tsx apps/web/src/app/[locale]/layout.tsx
git commit -m "feat(web): AuthProvider + QueryClient provider"
```

---

### Task 16: Login + register pages + shared auth form

**Files:**
- Create: `apps/web/src/components/auth/AuthForm.tsx`
- Create: `apps/web/src/components/auth/TelegramLoginButton.tsx`
- Create: `apps/web/src/app/[locale]/login/page.tsx`
- Create: `apps/web/src/app/[locale]/register/page.tsx`

- [ ] **Step 1: Telegram login button**

Create `apps/web/src/components/auth/TelegramLoginButton.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";

import { useAuth } from "@/lib/auth";

/**
 * Injects Telegram's Login Widget <script>. The widget calls a global callback
 * with the signed user payload, which we POST to /auth/telegram/widget.
 * Requires NEXT_PUBLIC_TELEGRAM_BOT and a BotFather /setdomain binding.
 */
export function TelegramLoginButton() {
  const ref = useRef<HTMLDivElement>(null);
  const { loginWithTelegram } = useAuth();
  const bot = process.env.NEXT_PUBLIC_TELEGRAM_BOT;

  useEffect(() => {
    if (!ref.current || !bot) return;
    const w = window as unknown as {
      onTelegramAuth?: (u: Record<string, unknown>) => void;
    };
    w.onTelegramAuth = (u) => void loginWithTelegram(u);
    const s = document.createElement("script");
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.async = true;
    s.setAttribute("data-telegram-login", bot);
    s.setAttribute("data-size", "large");
    s.setAttribute("data-radius", "12");
    s.setAttribute("data-onauth", "onTelegramAuth(user)");
    s.setAttribute("data-request-access", "write");
    ref.current.appendChild(s);
    return () => {
      ref.current?.replaceChildren();
    };
  }, [bot, loginWithTelegram]);

  if (!bot) return null;
  return <div ref={ref} />;
}
```

- [ ] **Step 2: Shared auth form**

Create `apps/web/src/components/auth/AuthForm.tsx` — a client form (email + password) using `react-hook-form` + `zod`, calling a passed `onSubmit`, showing errors. Mirror `PurchasePanel` input styling (`border-border bg-card focus:border-primary h-[46px] ...`). Include a `mode: "login" | "register"` prop controlling button label and the link row (to register/forgot or to login). Render `<TelegramLoginButton />` under a divider.

```tsx
"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { TelegramLoginButton } from "./TelegramLoginButton";
import { buttonStyles } from "@/lib/button";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});
type Values = z.infer<typeof schema>;

export function AuthForm({
  mode,
  locale,
  onSubmit,
}: {
  mode: "login" | "register";
  locale: string;
  onSubmit: (v: Values) => Promise<void>;
}) {
  const t = useTranslations("web.auth");
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  return (
    <form
      onSubmit={handleSubmit(async (v) => {
        setError(null);
        try {
          await onSubmit(v);
        } catch {
          setError(t(mode === "login" ? "loginError" : "registerError"));
        }
      })}
      className="flex flex-col gap-4"
    >
      <label className="block">
        <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">{t("email")}</span>
        <input
          type="email"
          {...register("email")}
          className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
        />
        {errors.email && <span className="mt-1 block text-xs text-[#FF6B6B]">{t("emailInvalid")}</span>}
      </label>
      <label className="block">
        <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">{t("password")}</span>
        <input
          type="password"
          {...register("password")}
          className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
        />
        {errors.password && (
          <span className="mt-1 block text-xs text-[#FF6B6B]">{t("passwordShort")}</span>
        )}
      </label>

      <button type="submit" disabled={isSubmitting} className={buttonStyles({ size: "lg" })}>
        {isSubmitting ? <Loader2 size={18} className="animate-spin" /> : t(mode)}
      </button>
      {error && <p className="text-center text-[13px] text-[#FF6B6B]">{error}</p>}

      <div className="text-tx-mute flex justify-between text-[13px]">
        {mode === "login" ? (
          <>
            <Link href={`/${locale}/register`} className="hover:text-tx">
              {t("toRegister")}
            </Link>
            <Link href={`/${locale}/auth/forgot`} className="hover:text-tx">
              {t("forgot")}
            </Link>
          </>
        ) : (
          <Link href={`/${locale}/login`} className="hover:text-tx">
            {t("toLogin")}
          </Link>
        )}
      </div>

      <div className="border-border/70 my-2 border-t" />
      <TelegramLoginButton />
    </form>
  );
}
```

> `@hookform/resolvers` must be present in `apps/web`. If not, add it: `pnpm --filter @yupay/web add @hookform/resolvers`.

- [ ] **Step 3: Pages**

Create `apps/web/src/app/[locale]/login/page.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { use } from "react";

import { AuthForm } from "@/components/auth/AuthForm";
import { useAuth } from "@/lib/auth";

export default function LoginPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const { login } = useAuth();
  const router = useRouter();
  return (
    <main className="mx-auto max-w-[420px] px-4 py-16">
      <h1 className="font-display mb-6 text-2xl font-bold tracking-[-0.02em]">Вход</h1>
      <AuthForm
        mode="login"
        locale={locale}
        onSubmit={async (v) => {
          await login(v.email, v.password);
          router.push(`/${locale}/account`);
        }}
      />
    </main>
  );
}
```

Create `apps/web/src/app/[locale]/register/page.tsx` analogously, calling `register(v.email, v.password, locale)` then routing to `/${locale}/account`. Use the localized `t("web.auth.loginTitle"/"registerTitle")` for the heading rather than a hardcoded string.

- [ ] **Step 4: Typecheck + lint**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/components/auth/**" "src/app/[locale]/login/**" "src/app/[locale]/register/**"`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/auth apps/web/src/app/[locale]/login apps/web/src/app/[locale]/register apps/web/package.json
git commit -m "feat(web): login + register pages with Telegram widget"
```

---

### Task 17: Forgot / reset / verify pages

**Files:**
- Create: `apps/web/src/app/[locale]/auth/forgot/page.tsx`
- Create: `apps/web/src/app/[locale]/auth/reset/page.tsx`
- Create: `apps/web/src/app/[locale]/auth/verify/page.tsx`

- [ ] **Step 1: Forgot page**

`forgot/page.tsx` — email input → `apiFetch("/auth/password/forgot", { method: "POST", anonymous: true, body: { email } })` → always show a neutral "если адрес зарегистрирован, мы отправили письмо" confirmation (non-enumerating). Use the same input styling and `buttonStyles`.

- [ ] **Step 2: Reset page**

`reset/page.tsx` — read `?token` via `useSearchParams`, new-password input → `apiFetch("/auth/password/reset", { method: "POST", anonymous: true, body: { token, new_password } })`; on success show "пароль изменён" + link to `/login`; on `ApiError` 401 show "ссылка недействительна или устарела".

- [ ] **Step 3: Verify page**

`verify/page.tsx` — read `?token`, on mount call `apiFetch("/auth/verify-email", { method: "POST", anonymous: true, body: { token } })` once; show success or error state. Use `useEffect` with a ref guard so it fires once.

```tsx
"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { apiFetch, ApiError } from "@/lib/client";

export default function VerifyPage() {
  const token = useSearchParams().get("token");
  const [state, setState] = useState<"pending" | "ok" | "error">("pending");
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current || !token) return;
    fired.current = true;
    apiFetch("/auth/verify-email", { method: "POST", anonymous: true, body: { token } })
      .then(() => {
        setState("ok");
      })
      .catch((e: unknown) => {
        setState(e instanceof ApiError ? "error" : "error");
      });
  }, [token]);

  return (
    <main className="mx-auto max-w-[420px] px-4 py-16 text-center">
      {state === "pending" && <p>Подтверждаем…</p>}
      {state === "ok" && <p>Email подтверждён ✓</p>}
      {state === "error" && <p>Ссылка недействительна или устарела.</p>}
    </main>
  );
}
```

> Replace hardcoded strings with `t("web.auth.*")` keys (added in Task 22). They are shown inline here for clarity.

- [ ] **Step 4: Typecheck + lint**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/app/[locale]/auth/**"`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/[locale]/auth
git commit -m "feat(web): forgot/reset/verify pages"
```

---

### Task 18: Account + order history pages

**Files:**
- Create: `apps/web/src/app/[locale]/account/page.tsx`
- Create: `apps/web/src/app/[locale]/account/orders/page.tsx`

- [ ] **Step 1: Account page**

`account/page.tsx` ("use client") — `useAuth()`; if `!user && !isLoading` redirect to `/${locale}/login` (via `useRouter` in an effect). Render profile (display name, email, locale, display currency) and, when `email && !email_verified` (note: `Me` has no verified flag — show a generic "не подтверждён? запросить письмо" action that re-triggers verification by re-registering is wrong; instead omit until backend exposes the flag). Keep it simple: show profile fields + a "Выйти" button (`logout()` then redirect) + a link to `/${locale}/account/orders`.

> The `MeOut` schema does not currently return `email_verified_at`. Either (a) add it to `MeOut` in `apps/api/src/yupay/modules/auth/schemas.py` and regenerate, or (b) drop the verify banner from v1. Pick (a) if cheap; the plan's default is (b) to keep scope tight — show no banner.

- [ ] **Step 2: Order history page**

`account/orders/page.tsx` ("use client") — auth-gated; `useQuery({ queryKey: ["orders"], queryFn: () => apiFetch<OrderListOut>("/orders") })`. Render a list of orders (id short, status badge, total, created date) each linking to `/${locale}/orders/${id}`. Define the `OrderListOut`/`OrderRow` types inline mirroring the backend `OrderListOut` (reuse the same shape the order-status page uses in Task 19 — keep one shared type in `apps/web/src/lib/orders-types.ts`).

- [ ] **Step 3: Shared order types**

Create `apps/web/src/lib/orders-types.ts`:

```typescript
export interface OrderItemOut {
  sku_id: string;
  sku_code: string;
  qty: number;
  unit_price_usd: string;
}

export interface OrderOut {
  id: string;
  status: string;
  currency: string;
  total_usd: string;
  total_charged: string;
  created_at: string;
  items: OrderItemOut[];
}

export interface OrderListOut {
  items: OrderOut[];
}
```

> Confirm field names against `apps/api/src/yupay/modules/orders/schemas.py` (`OrderOut`/`OrderListOut`) and adjust.

- [ ] **Step 4: Typecheck + lint**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/app/[locale]/account/**" "src/lib/orders-types.ts"`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/[locale]/account apps/web/src/lib/orders-types.ts
git commit -m "feat(web): account + order history pages"
```

---

### Task 19: Order-status page with polling

**Files:**
- Create: `apps/web/src/components/order/OrderStatus.tsx`
- Create: `apps/web/src/app/[locale]/orders/[orderId]/page.tsx`

- [ ] **Step 1: OrderStatus component**

Create `apps/web/src/components/order/OrderStatus.tsx` ("use client") — polls the order + deliveries. Works for both logged-in users (Bearer via `apiFetch`) and guests (pass `?email=` query param; for guests the request needs a Guest token — but guests returning from the acquirer have none in web localStorage). For v1 the page supports **logged-in users via Bearer** and **guests via the email query param against a Guest token if present in localStorage**; if neither is available the page shows "войдите, чтобы увидеть статус" with a login link. (Full guest-by-email-link tracking without a stored token is a follow-up; the email link can carry the order id and the page degrades gracefully.)

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/client";
import type { OrderOut } from "@/lib/orders-types";

const IN_MOTION = new Set(["pending_payment", "paid", "fulfilling", "fulfilled"]);

interface DeliveryOut {
  id: string;
  delivered_at: string | null;
  artifact: Record<string, string> | null;
}
interface DeliveryListOut {
  items: DeliveryOut[];
}

export function OrderStatus({ orderId, email }: { orderId: string; email?: string }) {
  const suffix = email ? `?email=${encodeURIComponent(email)}` : "";

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => apiFetch<OrderOut>(`/orders/${orderId}${suffix}`),
    refetchInterval: (q) => (q.state.data && IN_MOTION.has(q.state.data.status) ? 4000 : false),
  });

  const status = order.data?.status;
  const deliveries = useQuery({
    queryKey: ["deliveries", orderId],
    enabled: status === "delivered",
    queryFn: () => apiFetch<DeliveryListOut>(`/orders/${orderId}/deliveries${suffix}`),
  });

  if (order.isLoading) return <p className="text-tx-mute">Загрузка…</p>;
  if (order.isError || !order.data) return <p className="text-[#FF6B6B]">Заказ не найден.</p>;

  return (
    <div className="border-border rounded-2xl border bg-card p-6">
      <p className="text-tx-dim font-mono text-xs">#{order.data.id.slice(0, 8)}</p>
      <h2 className="font-display mt-2 text-xl font-bold">{statusLabel(order.data.status)}</h2>
      {status === "delivered" &&
        deliveries.data?.items.map((d) => (
          <pre key={d.id} className="bg-muted mt-4 overflow-x-auto rounded-lg p-3 text-sm">
            {JSON.stringify(d.artifact, null, 2)}
          </pre>
        ))}
    </div>
  );
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    pending_payment: "Ожидает оплаты",
    paid: "Оплачено",
    fulfilling: "Выполняется",
    fulfilled: "Готово",
    delivered: "Доставлено",
    refunded: "Возврат",
    cancelled: "Отменён",
    expired: "Истёк",
  };
  return map[s] ?? s;
}
```

> Replace `statusLabel` literals with `t("web.order.status.*")` keys in Task 22. Confirm the delivery artifact field name against `DeliveryOut` in `apps/api/src/yupay/modules/fulfillment/schemas.py`.

- [ ] **Step 2: Page**

Create `apps/web/src/app/[locale]/orders/[orderId]/page.tsx`:

```tsx
"use client";

import { useSearchParams } from "next/navigation";
import { use } from "react";

import { OrderStatus } from "@/components/order/OrderStatus";

export default function OrderPage({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = use(params);
  const email = useSearchParams().get("email") ?? undefined;
  return (
    <main className="mx-auto max-w-[560px] px-4 py-16">
      <OrderStatus orderId={orderId} email={email} />
    </main>
  );
}
```

- [ ] **Step 3: Typecheck + lint**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/components/order/**" "src/app/[locale]/orders/**"`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/order apps/web/src/app/[locale]/orders
git commit -m "feat(web): order-status page with polling"
```

---

### Task 20: Header auth state

**Files:**
- Modify: `apps/web/src/components/Header.tsx`
- Create: `apps/web/src/components/auth/AccountMenu.tsx`

- [ ] **Step 1: AccountMenu**

Create `apps/web/src/components/auth/AccountMenu.tsx` ("use client") — `useAuth()`; when `user`, render an avatar/initial + a small menu with links to `/${locale}/account`, `/${locale}/account/orders`, and a logout action; when no user, render a "Войти" link to `/${locale}/login`. While `isLoading`, render nothing (avoid flash).

- [ ] **Step 2: Mount in Header**

In `apps/web/src/components/Header.tsx`, add `<AccountMenu locale={locale} />` to the header's right-hand controls (next to `LocaleSwitcher`). If `Header` is a Server Component, keep `AccountMenu` as the `"use client"` island — importing a client component into a server component is fine.

- [ ] **Step 3: Typecheck + lint + build**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/components/**"`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/Header.tsx apps/web/src/components/auth/AccountMenu.tsx
git commit -m "feat(web): header account menu / login state"
```

---

### Task 21: PurchasePanel — user-owned orders + route to status

**Files:**
- Modify: `apps/web/src/components/store/PurchasePanel.tsx`

- [ ] **Step 1: Use the user token when signed in**

In `PurchasePanel.tsx`, import `useAuth` and `getAccessToken`/`apiFetch` from the client. Change `pay()` so that:
- If a logged-in user is present (`getAccessToken()` returns a token and `useAuth().user`), skip the `/auth/guest` step and create the order with `Authorization: Bearer <token>` (no `guest_email`), then the payment intent with the Bearer token.
- Otherwise keep the existing guest path unchanged.

Concretely, replace the guest-token acquisition + `auth` header construction:

```tsx
const { user } = useAuth();
// ...inside pay():
let auth: Record<string, string>;
let guestEmailField: Record<string, string> = {};
let intentEmailQuery = "";
if (getAccessToken() && user) {
  auth = { Authorization: `Bearer ${getAccessToken() ?? ""}` };
} else {
  const g = await fetch(`${API}/api/v1/auth/guest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!g.ok) throw new Error("guest");
  const { access_token } = (await g.json()) as { access_token: string };
  auth = { Authorization: `Guest ${access_token}` };
  guestEmailField = { guest_email: email };
  intentEmailQuery = `?email=${encodeURIComponent(email)}`;
}
```

Use `guestEmailField` in the order body (spread it) and `intentEmailQuery` on the intents URL. Keep `email` required only for the guest path (when logged in, the account email is used server-side).

- [ ] **Step 2: Route to the status page on success**

Replace the static `done` success panel's behavior: after a successful intent, push to the order-status page so the buyer gets live tracking. Add `useRouter` + `useParams`/the `locale` prop:

```tsx
// after setDone(...) succeeds, or instead of the static panel:
const trackHref = `/${locale}/orders/${order.id}${intentEmailQuery}`;
// If there is an intent_url, send to the acquirer; the return URL should be trackHref.
// Render a "Перейти к оплате" linking to intent_url AND a "Статус заказа" link to trackHref.
```

Keep the existing success panel but add a **"Статус заказа"** link to `trackHref` beneath the pay button so both guests and users can reach tracking.

- [ ] **Step 3: Typecheck + lint**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/components/store/PurchasePanel.tsx"`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/store/PurchasePanel.tsx
git commit -m "feat(web): user-owned checkout + link to order status"
```

---

### Task 22: i18n keys (ru/en/uz)

**Files:**
- Modify: `packages/i18n/locales/ru/web.json`, `packages/i18n/locales/en/web.json`, `packages/i18n/locales/uz/web.json`

- [ ] **Step 1: Add namespaces**

Add `auth`, `account`, and `order` namespaces to each locale's `web.json`. Keys used across Tasks 16-21:

```jsonc
// auth
"auth": {
  "loginTitle": "...", "registerTitle": "...",
  "login": "...", "register": "...",
  "email": "...", "password": "...",
  "emailInvalid": "...", "passwordShort": "...",
  "loginError": "...", "registerError": "...",
  "toRegister": "...", "toLogin": "...", "forgot": "...",
  "forgotTitle": "...", "forgotSent": "...",
  "resetTitle": "...", "resetDone": "...", "resetInvalid": "...",
  "verifyPending": "...", "verifyOk": "...", "verifyError": "..."
},
// account
"account": {
  "title": "...", "email": "...", "currency": "...", "locale": "...",
  "orders": "...", "logout": "...", "login": "...", "empty": "..."
},
// order
"order": {
  "trackTitle": "...", "track": "...", "notFound": "...", "loading": "...",
  "status": {
    "pending_payment": "...", "paid": "...", "fulfilling": "...",
    "fulfilled": "...", "delivered": "...", "refunded": "...",
    "cancelled": "...", "expired": "..."
  }
}
```

Fill **all three** locales with real translations (ru/en/uz). Then replace the inline hardcoded strings in Tasks 16/17/19 components with `t("web.auth.*")` / `t("web.order.*")` calls.

- [ ] **Step 2: Verify no missing keys**

Run: `cd /Users/macbook_uz/Projects/yupay && node -e "const r=require('./packages/i18n/locales/ru/web.json'),e=require('./packages/i18n/locales/en/web.json'),u=require('./packages/i18n/locales/uz/web.json');const keys=o=>Object.keys(o).flatMap(k=>typeof o[k]==='object'?Object.keys(o[k]).map(s=>k+'.'+s):[k]);console.log('ru',keys(r).length,'en',keys(e).length,'uz',keys(u).length)"`
Expected: equal counts across locales.

- [ ] **Step 3: Typecheck whole web app**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/**/*.{ts,tsx}" && pnpm exec prettier --check "src/**/*.{ts,tsx}"`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add packages/i18n/locales apps/web/src
git commit -m "feat(web): i18n for auth/account/order (ru/en/uz)"
```

---

## Phase 4 — Docs + final gate

### Task 23: ADRs, module-map, cache-keys, sequence diagrams

**Files:**
- Create: `docs/decisions/0026-web-password-auth.md`
- Create: `docs/decisions/0027-resend-email-channel.md`
- Modify: `docs/architecture/module-map.md`, `docs/architecture/cache-keys.md`
- Create: `docs/architecture/sequence-diagrams/web-auth.mmd`, `docs/architecture/sequence-diagrams/web-order-tracking.mmd`

- [ ] **Step 1: ADR 0026 — web password auth**

Write `docs/decisions/0026-web-password-auth.md` using the MADR template (`docs/decisions/0000-template.md`): the email/password + Telegram-widget dual auth, argon2id, the stateless `email_verify`/`password_reset` JWTs + one-time Redis marker, the **localStorage + refresh-rotation** session choice (with httpOnly-cookie/BFF named as future hardening), and the v1 limitations (separate Telegram vs email accounts; guest-order linking deferred).

- [ ] **Step 2: ADR 0027 — Resend email channel**

Write `docs/decisions/0027-resend-email-channel.md`: the Resend dependency, the four templates, where auth emails (request path) vs order emails (notifications dispatch) are sent, and the best-effort/non-blocking failure policy.

- [ ] **Step 3: module-map + cache-keys**

- In `docs/architecture/module-map.md`: note `auth` gains email/password flows; `notifications` gains the email channel (reads order + user data).
- In `docs/architecture/cache-keys.md`: add `auth:pwreset:{jti}` (TTL = email-token TTL, one-time) and `auth:ipguard:{bucket}:{ip}` (TTL = guard window).

- [ ] **Step 4: Sequence diagrams**

`web-auth.mmd` — register → verify email; login; forgot → reset. `web-order-tracking.mmd` — checkout → acquirer → return → poll order/deliveries → delivered.

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/0026-web-password-auth.md docs/decisions/0027-resend-email-channel.md docs/architecture
git commit -m "docs: ADRs + module-map + cache-keys + sequence diagrams for web accounts"
```

---

### Task 24: Full gate + manual verification

- [ ] **Step 1: Backend gate**

Run: `cd apps/api && uv run pytest tests/unit/test_auth_security_password.py tests/unit/test_auth_jwt_email_tokens.py tests/unit/test_email_templates.py tests/contract/test_resend_email.py tests/integration/test_auth_password.py tests/integration/test_auth_ip_guard.py tests/integration/test_order_emails.py --cov=yupay.modules.auth --cov=yupay.modules.notifications --cov-report=term-missing -q`
Expected: all PASS; `auth` coverage ≥80%.

- [ ] **Step 2: Lint/typecheck everything**

Run: `make lint typecheck` (or scoped: `cd apps/api && uv run ruff check . && uv run mypy src`; `cd apps/web && pnpm exec tsc --noEmit && pnpm exec eslint "src/**/*.{ts,tsx}" && pnpm exec prettier --check "src/**/*.{ts,tsx}"`)
Expected: clean.

- [ ] **Step 3: Recreate API + run migration on the dev stack**

Run: `docker compose -p yupay-dev up -d --no-deps api && make migrate`
Then restart web if needed: `docker compose -p yupay-dev restart web`.

- [ ] **Step 4: Manual verification (web at http://localhost:3000)**

- Register at `/ru/register` → lands on `/ru/account`; `me` shows the email.
- Logout, then login at `/ru/login` → account loads.
- Forgot at `/ru/auth/forgot` → neutral confirmation (check the API logs / Resend test inbox if a key is set).
- Buy from a brand page while logged in → order created under the account → appears in `/ru/account/orders` and `/ru/orders/{id}` polls to a terminal status.
- Buy as guest → success panel shows a "Статус заказа" link to `/ru/orders/{id}?email=…`.
- Repeat a smoke check on `/en` and `/uz` (strings localized).

- [ ] **Step 5: Final commit / confirm clean**

Run: `git status` (expect clean) and confirm `main` is ready. Push only on explicit user go-ahead.

---

## Self-Review notes (author)

- **Spec coverage:** register/login/verify/forgot/reset (T7-T10), email channel + templates (T4-T5), order emails (T12), migration (T6), Telegram widget reuse (T16/T15), account + history (T18), order tracking incl. guest (T19/T21), localStorage session (T14), argon2id (T2), Redis one-time marker + IP guard (T10/T11), i18n ru/en/uz (T22), ADRs/cache-keys/module-map/diagrams (T23), OpenAPI regen (T13), tests + gate (T24). All spec §9 DoD items mapped.
- **Known follow-ups (documented, out of slice 1):** full guest-by-email tracking without a stored token degrades gracefully (T19); `email_verified_at` not surfaced in `MeOut` → verify banner deferred (T18); cart + search are separate slices.
- **Credential dependencies:** Resend key + domain, Telegram bot username + `NEXT_PUBLIC_TELEGRAM_BOT` + BotFather `/setdomain`. Until provided, email sends are exercised via `respx` only and the Telegram button hides itself.
