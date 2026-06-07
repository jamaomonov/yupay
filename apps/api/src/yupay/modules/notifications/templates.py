"""Plain, dependency-free email template builders.

Each returns an :class:`EmailContent` (subject + html + text). Copy is in
Russian (the storefront's default locale); per-locale copy can be layered later.
Keep these simple — no templating engine, just f-strings — so they are trivial
to unit-test and review.
"""

from __future__ import annotations

import html

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


def order_delivered_email(
    *, order_id: str, link: str, codes: list[str] | None = None
) -> EmailContent:
    """Order-delivered notification for guest buyers.

    When ``codes`` is given (voucher/license keys, or a 'credited' line for
    top-ups) they are rendered inline in the body so the buyer gets their goods
    straight from the email. Otherwise the email just links to the order page.
    """
    short = order_id[:8]
    if codes:
        html_codes = "".join(
            '<div style="font-family:monospace;font-size:15px;background:#f4f4f5;'
            f'border-radius:8px;padding:10px 12px;margin:6px 0">{html.escape(c)}</div>'
            for c in codes
        )
        body_html = (
            "<h2>Ваш заказ выполнен</h2>"
            f"<p>Заказ <b>#{short}</b> доставлен:</p>"
            f"{html_codes}"
            f'<p style="margin-top:16px"><a href="{link}">Открыть заказ</a></p>'
        )
        text = f"Заказ #{short} выполнен.\n\n" + "\n".join(codes) + f"\n\nОткрыть: {link}"
    else:
        body_html = (
            "<h2>Ваш заказ выполнен</h2>"
            f"<p>Заказ <b>#{short}</b> доставлен. Откройте, чтобы увидеть артефакт:</p>"
            f'<p><a href="{link}">Открыть заказ</a></p>'
        )
        text = f"Заказ #{short} выполнен. Откройте: {link}"
    return EmailContent(
        subject=f"Заказ #{short} выполнен — YuPay",
        html=_wrap(body_html),
        text=text,
    )


__all__ = [
    "EmailContent",
    "order_confirmation_email",
    "order_delivered_email",
    "password_reset_email",
    "verify_email_email",
]
