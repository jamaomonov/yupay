"""Branded, email-client-safe template builders.

Each returns an :class:`EmailContent` (subject + html + text). Copy is in
Russian (the storefront's default locale); per-locale copy can be layered later.

The HTML is deliberately hand-written with table-based layout, inline styles and
a "bulletproof" CTA button so it renders consistently across Gmail, Apple Mail
and Outlook. The brand logo is loaded from a public PNG URL (email clients don't
render SVG); when no URL is configured it degrades to a text wordmark.
"""

from __future__ import annotations

import datetime
import html

from pydantic import BaseModel, ConfigDict

from yupay.core.config import get_settings

# --- Brand palette (mirrors apps/web globals.css) ---
_BRAND_DARK = "#0A0D1A"
_LIME = "#AAFF33"
_ON_LIME = "#05080F"
_PAGE_BG = "#F4F5F7"
_CARD_BG = "#FFFFFF"
_BORDER = "#E6E8EC"
_HEADING = "#0F1117"
_BODY = "#4A4F5C"
_MUTED = "#8A90A0"
_LINK = "#3D7A00"
_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif,"
    "'Apple Color Emoji','Segoe UI Emoji'"
)


class EmailContent(BaseModel):
    """Rendered email: subject + html + plain-text bodies."""

    model_config = ConfigDict(frozen=True)

    subject: str
    html: str
    text: str


def _site_url() -> str:
    """Public storefront URL used for the header logo link."""
    return get_settings().web_base_url.rstrip("/") or "https://yupay.uz"


def _logo_html() -> str:
    """Header logo: PNG when a public URL is available, else a text wordmark."""
    s = get_settings()
    src = s.email_logo_url or (
        f"{s.web_base_url.rstrip('/')}/logo/email-logo.png" if s.web_base_url else ""
    )
    site = _site_url()
    if src:
        img = (
            f'<img src="{html.escape(src, quote=True)}" width="128" alt="YuPay" '
            'style="display:block;margin:0 auto;height:38px;width:auto;border:0;'
            'line-height:38px;outline:none;text-decoration:none;">'
        )
        return f'<a href="{site}" target="_blank" style="text-decoration:none;">{img}</a>'
    return (
        f'<a href="{site}" target="_blank" '
        f'style="font-family:{_FONT};font-size:24px;font-weight:800;letter-spacing:-0.5px;'
        f'color:#FFFFFF;text-decoration:none;">Yu<span style="color:{_LIME}">Pay</span></a>'
    )


def _button(*, href: str, label: str) -> str:
    """Bulletproof lime CTA button (with an MSO fallback for Outlook)."""
    safe_href = html.escape(href, quote=True)
    safe_label = html.escape(label)
    return (
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0" '
        'style="margin:28px auto 4px;"><tr>'
        f'<td align="center" bgcolor="{_LIME}" style="border-radius:12px;">'
        "<!--[if mso]>"
        f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="{safe_href}" '
        'style="height:48px;v-text-anchor:middle;width:280px;" arcsize="25%" '
        f'fillcolor="{_LIME}" stroke="f"><center style="color:{_ON_LIME};'
        f'font-family:{_FONT};font-size:15px;font-weight:700;">{safe_label}</center>'
        "</v:roundrect><![endif]-->"
        "<!--[if !mso]><!-- -->"
        f'<a href="{safe_href}" target="_blank" '
        f'style="display:inline-block;padding:15px 34px;font-family:{_FONT};font-size:15px;'
        f'font-weight:700;line-height:18px;color:{_ON_LIME};text-decoration:none;border-radius:12px;">'
        f"{safe_label}</a>"
        "<!--<![endif]-->"
        "</td></tr></table>"
    )


def _fallback_link(href: str) -> str:
    """Muted 'copy the link' block shown under the CTA button."""
    safe_href = html.escape(href, quote=True)
    return (
        f'<p style="margin:20px 0 0;font-family:{_FONT};font-size:13px;line-height:20px;'
        f'color:{_MUTED};">Кнопка не работает? Скопируйте ссылку в браузер:</p>'
        f'<p style="margin:6px 0 0;font-family:{_FONT};font-size:13px;line-height:20px;'
        f'word-break:break-all;"><a href="{safe_href}" target="_blank" '
        f'style="color:{_LINK};text-decoration:underline;">{safe_href}</a></p>'
    )


def _layout(
    *,
    preheader: str,
    heading: str,
    body_html: str,
) -> str:
    """Wrap inner content into the branded, responsive email shell."""
    year = datetime.datetime.now(tz=datetime.UTC).year
    site = _site_url()
    return (
        '<!DOCTYPE html><html lang="ru" xmlns:v="urn:schemas-microsoft-com:vml">'
        '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        "<title>YuPay</title></head>"
        f'<body style="margin:0;padding:0;background:{_PAGE_BG};">'
        f'<span style="display:none!important;visibility:hidden;opacity:0;color:transparent;'
        f'height:0;width:0;font-size:1px;line-height:1px;">{html.escape(preheader)}</span>'
        f'<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'bgcolor="{_PAGE_BG}" style="background:{_PAGE_BG};"><tr>'
        '<td align="center" style="padding:28px 12px;">'
        '<table role="presentation" width="520" border="0" cellpadding="0" cellspacing="0" '
        'style="width:520px;max-width:520px;">'
        # header
        f'<tr><td style="background:{_BRAND_DARK};border-radius:16px 16px 0 0;'
        f'padding:24px 28px;text-align:center;">{_logo_html()}</td></tr>'
        # body card
        f'<tr><td style="background:{_CARD_BG};padding:34px 30px;'
        f'border-left:1px solid {_BORDER};border-right:1px solid {_BORDER};">'
        f'<h1 style="margin:0 0 12px;font-family:{_FONT};font-size:21px;line-height:28px;'
        f'font-weight:700;color:{_HEADING};">{html.escape(heading)}</h1>'
        f"{body_html}</td></tr>"
        # footer
        f'<tr><td style="background:{_BRAND_DARK};border-radius:0 0 16px 16px;'
        f'padding:22px 28px;text-align:center;">'
        f'<p style="margin:0;font-family:{_FONT};font-size:13px;line-height:20px;color:#C8CDD8;">'
        f'Yu<span style="color:{_LIME}">Pay</span> — цифровые товары и пополнения</p>'
        f'<p style="margin:8px 0 0;font-family:{_FONT};font-size:12px;line-height:18px;color:#6C7284;">'
        f"Это письмо отправлено автоматически, отвечать на него не нужно.<br>"
        f'© {year} YuPay · <a href="{site}" target="_blank" style="color:#8A90A0;'
        f'text-decoration:underline;">yupay.uz</a></p>'
        "</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def _paragraph(text_html: str) -> str:
    """A standard body paragraph."""
    return (
        f'<p style="margin:0 0 16px;font-family:{_FONT};font-size:15px;line-height:23px;'
        f'color:{_BODY};">{text_html}</p>'
    )


def verify_email_email(*, link: str) -> EmailContent:
    """Email-verification message with a confirmation link."""
    body = (
        _paragraph(
            "Спасибо за регистрацию в YuPay. Остался один шаг — подтвердите свой адрес электронной почты, чтобы активировать аккаунт."
        )
        + _button(href=link, label="Подтвердить email")
        + _fallback_link(link)
    )
    return EmailContent(
        subject="Подтвердите ваш email — YuPay",
        html=_layout(
            preheader="Подтвердите email, чтобы активировать аккаунт YuPay.",
            heading="Подтверждение email",
            body_html=body,
        ),
        text=(
            "Подтверждение email — YuPay\n\n"
            "Спасибо за регистрацию. Подтвердите свой адрес, открыв ссылку:\n"
            f"{link}\n"
        ),
    )


def password_reset_email(*, link: str) -> EmailContent:
    """Password-reset message with a reset link."""
    body = (
        _paragraph(
            "Вы запросили сброс пароля для аккаунта YuPay. Нажмите кнопку ниже, чтобы задать новый пароль. Ссылка действует 30 минут."
        )
        + _button(href=link, label="Задать новый пароль")
        + _fallback_link(link)
        + _paragraph(
            f'<span style="font-size:13px;color:{_MUTED};">Если вы не запрашивали сброс — '
            "просто проигнорируйте это письмо, пароль останется прежним.</span>"
        )
    )
    return EmailContent(
        subject="Сброс пароля — YuPay",
        html=_layout(
            preheader="Ссылка для сброса пароля действует 30 минут.",
            heading="Сброс пароля",
            body_html=body,
        ),
        text=(
            "Сброс пароля — YuPay\n\n"
            "Вы запросили сброс пароля. Ссылка действует 30 минут:\n"
            f"{link}\n\n"
            "Если это были не вы — проигнорируйте письмо.\n"
        ),
    )


def merchant_confirm_email(*, link: str) -> EmailContent:
    """Confirm a merchant operator's address after an open registration.

    Registration is open (spec §11), so this link is the only thing between a
    stranger and a mailbox that is not theirs — which is why the copy names
    what happens if they did not register: nothing, if they ignore it.

    Says nothing about deposits, delivery times or pricing mechanics: the
    landing-copy rules apply to mail we send about the same product.
    """
    body = (
        _paragraph(
            "Подтвердите адрес, чтобы войти в кабинет для партнёров YuPay. Ссылка действует сутки."
        )
        + _button(href=link, label="Подтвердить адрес")
        + _fallback_link(link)
        + _paragraph(
            f'<span style="font-size:13px;color:{_MUTED};">Если вы не регистрировались, '
            "просто не открывайте ссылку — без подтверждения аккаунт не активен.</span>"
        )
    )
    return EmailContent(
        subject="Подтвердите адрес — кабинет YuPay для партнёров",
        html=_layout(
            preheader="Подтвердите адрес и войдите в кабинет.",
            heading="Подтверждение адреса",
            body_html=body,
        ),
        text=(
            "Подтвердите адрес — кабинет YuPay для партнёров\n\n"
            "Ссылка действует сутки:\n"
            f"{link}\n\n"
            "Если вы не регистрировались — просто проигнорируйте это письмо.\n"
        ),
    )


def merchant_password_reset_email(*, link: str) -> EmailContent:
    """A reset link for a merchant operator who cannot get in.

    Named as a *request* the reader may not have made, and says what to do
    about that: the endpoint answers the same to everybody, so this mail is
    also what an address-prober's target receives. "Ignore it and nothing
    happens" is the only honest instruction, and it has to be in the mail
    rather than only in our heads.

    Thirty minutes, and it says so: a reset link is read in the sitting it was
    asked for, unlike a registration confirmation.
    """
    body = (
        _paragraph(
            "Кто-то запросил сброс пароля для кабинета YuPay для партнёров. "
            "Ссылка действует 30 минут."
        )
        + _button(href=link, label="Задать новый пароль")
        + _fallback_link(link)
        + _paragraph(
            f'<span style="font-size:13px;color:{_MUTED};">Если это были не вы — '
            "просто не открывайте ссылку. Пароль останется прежним, и в аккаунте "
            "ничего не изменится.</span>"
        )
    )
    return EmailContent(
        subject="Сброс пароля — кабинет YuPay для партнёров",
        html=_layout(
            preheader="Ссылка на смену пароля действует 30 минут.",
            heading="Сброс пароля",
            body_html=body,
        ),
        text=(
            "Сброс пароля — кабинет YuPay для партнёров\n\n"
            "Ссылка действует 30 минут:\n"
            f"{link}\n\n"
            "Если это были не вы — просто проигнорируйте письмо, пароль не изменится.\n"
        ),
    )


#: What each cabinet security notice says it is. Prose per event rather than
#: one "что-то изменилось": a notice a reader cannot act on is a notice they
#: learn to ignore, and the whole point is that an unexpected one is noticed.
_MERCHANT_SECURITY_LINES: dict[str, tuple[str, str]] = {
    "api_key_created": (
        "Выпущен новый ключ API",
        "В вашем кабинете выпустили новый ключ API",
    ),
    "api_key_revoked": (
        "Ключ API отозван",
        "В вашем кабинете отозвали ключ API",
    ),
    "webhook_url_changed": (
        "Изменён адрес вебхука",
        "В вашем кабинете изменили адрес, на который мы отправляем вебхуки",
    ),
    "webhook_secret_rotated": (
        "Изменён секрет подписи вебхуков",
        "В вашем кабинете сменили секрет, которым мы подписываем вебхуки",
    ),
    "webhook_disabled": (
        "Вебхук отключён",
        "В вашем кабинете отключили вебхук — доставки прекращены",
    ),
}


def merchant_security_email(*, event: str, detail: str = "") -> EmailContent:
    """Tell a merchant's operators that a credential or an endpoint changed.

    No link and no button: there is nothing to click that is safer than what
    the reader would do anyway, and a "was this you? / no" link in a mail is
    an endpoint an attacker can reach too. The instruction is to sign in, or
    to write to support — both of which they reach by their own route.

    ``detail`` is shown verbatim and is a key id or a webhook host: enough to
    tell "the key I just made" from "a key I did not", never a secret.
    """
    heading, sentence = _MERCHANT_SECURITY_LINES.get(
        event, ("Изменение в кабинете", "В вашем кабинете изменились настройки доступа")
    )
    named = f"{sentence}: {detail}." if detail else f"{sentence}."
    body = _paragraph(named) + _paragraph(
        f'<span style="font-size:13px;color:{_MUTED};">Если это были не вы — '
        "сразу отзовите ключи в кабинете и напишите в поддержку.</span>"
    )
    return EmailContent(
        subject=f"{heading} — кабинет YuPay для партнёров",
        html=_layout(preheader=named, heading=heading, body_html=body),
        text=(
            f"{heading} — кабинет YuPay для партнёров\n\n{named}\n\n"
            "Если это были не вы — сразу отзовите ключи в кабинете "
            "и напишите в поддержку.\n"
        ),
    )


def partner_invite_email(*, link: str) -> EmailContent:
    """Approval notice for a new affiliate partner, with the set-password link.

    Says what happens next and how long the link lasts, because a partner who
    opens it after it expires has no way to tell whether they were rejected or
    simply late.
    """
    body = (
        _paragraph(
            "Ваша заявка в партнёрскую программу YuPay одобрена. Нажмите кнопку ниже, "
            "чтобы задать пароль и войти в панель. Ссылка действует 30 минут — если не "
            "успеете, напишите нам, и мы пришлём новую."
        )
        + _button(href=link, label="Задать пароль")
        + _fallback_link(link)
        + _paragraph(
            f'<span style="font-size:13px;color:{_MUTED};">В панели вы найдёте свой '
            "промокод, статистику и баланс.</span>"
        )
    )
    return EmailContent(
        subject="Заявка одобрена — партнёрская программа YuPay",
        html=_layout(
            preheader="Задайте пароль и войдите в партнёрскую панель.",
            heading="Добро пожаловать в программу",
            body_html=body,
        ),
        text=(
            "Заявка одобрена — партнёрская программа YuPay\n\n"
            "Задайте пароль и войдите в панель. Ссылка действует 30 минут:\n"
            f"{link}\n\n"
            "Если ссылка устарела — напишите нам, пришлём новую.\n"
        ),
    )


def order_confirmation_email(*, order_id: str, link: str) -> EmailContent:
    """Order-created confirmation for guest buyers."""
    short = order_id[:8]
    body = (
        _paragraph(
            f'Мы приняли ваш заказ <b style="color:{_HEADING}">#{html.escape(short)}</b> и уже готовим его к выдаче. '
            "Отслеживайте статус на странице заказа — мы уведомим вас, как только всё будет готово."
        )
        + _button(href=link, label="Открыть заказ")
        + _fallback_link(link)
        # A guest buyer keeps nothing else: no account, and the browser tab is
        # usually gone. Say plainly that this letter is the key, so it doesn't
        # get deleted along with the rest of the promo mail.
        + _paragraph("Сохраните это письмо — по ссылке выше вы откроете заказ с любого устройства.")
    )
    return EmailContent(
        subject=f"Заказ #{short} принят — YuPay",
        html=_layout(
            preheader=f"Заказ #{short} принят и готовится к выдаче.",
            heading="Спасибо за заказ!",
            body_html=body,
        ),
        text=(
            f"Заказ #{short} принят — YuPay\n\n"
            f"Мы приняли ваш заказ #{short} и готовим его к выдаче.\n"
            f"Статус заказа: {link}\n\n"
            "Сохраните это письмо — по ссылке выше вы откроете заказ с любого устройства.\n"
        ),
    )


def _codes_block(codes: list[str]) -> str:
    """Render voucher/license keys as monospace chips (secrets to copy)."""
    rows = ""
    for code in codes:
        rows += (
            '<tr><td style="background:#F4F5F7;border:1px solid '
            f"{_BORDER};border-radius:10px;padding:13px 15px;font-family:ui-monospace,"
            "SFMono-Regular,Menlo,Consolas,monospace;font-size:15px;line-height:20px;"
            f'color:{_HEADING};word-break:break-all;">{html.escape(code)}</td></tr>'
            '<tr><td style="height:8px;line-height:8px;font-size:8px;">&nbsp;</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'style="margin:8px 0 20px;">{rows}</table>'
    )


def _credited_block(lines: list[str]) -> str:
    """Render top-up receipts as info rows with a check mark (not a secret code)."""
    rows = ""
    for line in lines:
        rows += (
            '<tr><td style="background:#F4F5F7;border:1px solid '
            f"{_BORDER};border-radius:10px;padding:13px 15px;font-family:{_FONT};"
            f'font-size:14px;line-height:20px;color:{_HEADING};">'
            f'<span style="color:{_LINK};font-weight:700;">&#10003;</span>&nbsp;&nbsp;'
            f"{html.escape(line)}</td></tr>"
            '<tr><td style="height:8px;line-height:8px;font-size:8px;">&nbsp;</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'style="margin:8px 0 20px;">{rows}</table>'
    )


def order_delivered_email(
    *,
    order_id: str,
    link: str,
    codes: list[str] | None = None,
    credited: list[str] | None = None,
) -> EmailContent:
    """Order-delivered notification for guest buyers.

    Two kinds of artifacts can be surfaced inline so the buyer gets their goods
    straight from the email:

    - ``codes``: voucher / license keys — secrets rendered as monospace chips
      with a "save them somewhere safe" copy.
    - ``credited``: top-up receipts (e.g. "Зачислено · ID игрока: 42") — rendered
      as info rows, since a top-up delivers no code, only a confirmation that the
      account was credited.

    When neither is given the email just links to the order page.
    """
    short = order_id[:8]
    has_codes = bool(codes)
    has_credited = bool(credited)

    if has_codes and has_credited:
        intro = "выполнен. Ваши коды и детали заказа ниже:"
    elif has_codes:
        intro = "выполнен. Ваши коды ниже — сохраните их в надёжном месте:"
    elif has_credited:
        intro = "выполнен — средства зачислены на ваш аккаунт:"
    else:
        intro = "выполнен. Откройте страницу заказа, чтобы получить свой цифровой товар."

    body = _paragraph(f'Ваш заказ <b style="color:{_HEADING}">#{html.escape(short)}</b> {intro}')
    if has_codes:
        body += _codes_block(codes or [])
    if has_credited:
        body += _credited_block(credited or [])
    body += _button(href=link, label="Открыть заказ")
    # Soft review ask: the order page already surfaces the review form, so this
    # just nudges the buyer there — real reviews are the strongest trust signal.
    review_href = html.escape(link, quote=True)
    body += _paragraph(
        f'Всё прошло гладко? <a href="{review_href}" target="_blank" '
        f'style="color:{_LINK};text-decoration:underline;">Оцените заказ</a> — '
        "ваш отзыв помогает другим игрокам выбрать YuPay."
    )
    if not (has_codes or has_credited):
        body += _fallback_link(link)

    text_lines: list[str] = []
    if has_codes:
        text_lines.append("Ваши коды:")
        text_lines.extend(codes or [])
    if has_credited:
        if has_codes:
            text_lines.append("")
        text_lines.extend(credited or [])
    if not (has_codes or has_credited):
        text_lines.append(f"Ваш заказ #{short} выполнен.")
    text = (
        f"Заказ #{short} выполнен — YuPay\n\n"
        + "\n".join(text_lines)
        + f"\n\nОткрыть заказ: {link}\n"
        + "Всё прошло гладко? Оцените заказ на его странице — это помогает другим игрокам.\n"
    )

    preheader = (
        f"Заказ #{short} выполнен — средства зачислены."
        if (has_credited and not has_codes)
        else f"Заказ #{short} выполнен."
    )
    return EmailContent(
        subject=f"Заказ #{short} выполнен — YuPay",
        html=_layout(preheader=preheader, heading="Ваш заказ выполнен", body_html=body),
        text=text,
    )


def merchant_webhook_disabled_email(*, host: str, failures: int, last_error: str) -> EmailContent:
    """Tell a reseller's operator we stopped delivering to their endpoint.

    Sent exactly once per auto-disable (M3a Task 4), never per failed attempt.
    It has to answer three questions before anyone opens a ticket: which
    endpoint, why we stopped, and what turns it back on.

    Only the **host** is named, not the configured URL: a webhook path can
    carry a token (``merchants.models.WEBHOOK_URL_MAX`` is sized for one), and
    an email goes through a third-party provider and sits in a mailbox. The
    host is enough to identify the endpoint for someone who configured it.

    Args:
        host: The endpoint's hostname.
        failures: The consecutive-failure count that tripped the threshold.
        last_error: Our own short description of the final failure — already
            truncated by the caller and free of merchant credentials.

    Returns:
        The rendered subject, HTML and plain-text bodies.
    """
    body = (
        _paragraph(
            f"Мы приостановили отправку webhook-уведомлений на <b>{html.escape(host)}</b>: "
            f"подряд не удалось доставить {failures} событий."
        )
        + _paragraph(
            f'<span style="font-size:13px;color:{_MUTED};">Последняя ошибка: '
            f"{html.escape(last_error)}</span>"
        )
        + _paragraph(
            "События за это время не потеряны — актуальный статус любого заказа "
            "доступен в API: <code>GET /merchant/v1/orders/{merchant_order_id}</code>."
        )
        + _paragraph(
            "Когда эндпоинт снова заработает, напишите нам — мы включим отправку "
            "обратно. Секрет подписи при этом не меняется."
        )
    )
    return EmailContent(
        subject="Отправка webhook приостановлена — YuPay",
        html=_layout(
            preheader=f"Webhook на {host} отключён после {failures} неудачных попыток.",
            heading="Webhook отключён",
            body_html=body,
        ),
        text=(
            "Отправка webhook приостановлена — YuPay\n\n"
            f"Мы приостановили отправку уведомлений на {host}: "
            f"подряд не удалось доставить {failures} событий.\n"
            f"Последняя ошибка: {last_error}\n\n"
            "События не потеряны — статус заказа доступен в API: "
            "GET /merchant/v1/orders/{merchant_order_id}\n\n"
            "Когда эндпоинт заработает, напишите нам — мы включим отправку обратно. "
            "Секрет подписи не меняется.\n"
        ),
    )


__all__ = [
    "EmailContent",
    "merchant_confirm_email",
    "merchant_password_reset_email",
    "merchant_security_email",
    "merchant_webhook_disabled_email",
    "order_confirmation_email",
    "order_delivered_email",
    "partner_invite_email",
    "password_reset_email",
    "verify_email_email",
]
