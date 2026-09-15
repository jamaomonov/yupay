"""Telling a merchant's operators that something security-relevant changed.

Spec §11: mail on key created / revoked and on a webhook URL change — and
nothing else. A cabinet that mailed about every action would train its readers
to ignore the mail, which is the failure mode this is trying to avoid: the
only thing these messages have to accomplish is that a credential issued by
somebody who should not have issued it is **noticed**.

Sent to every operator on the account rather than to whoever clicked. One
merchant has one operator today and the schema allows more; a notice that
reached only the person who made the change would be worth nothing on the day
it matters.

**Best effort, and in the request's own transaction.** A send that fails is a
log line, never a failed request: the change has already happened and refusing
it afterwards would leave the caller unable to tell what state they are in.
The same trade `register` makes, for the same reason.
"""

from __future__ import annotations

from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.merchants.models import MerchantUser
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import merchant_security_email

log = get_logger("yupay.merchants.cabinet_notify")

#: The closed vocabulary. A literal rather than a bare string so that adding a
#: sixth means adding its copy in the same change — a notice whose body says
#: "что-то изменилось" is a notice nobody can act on.
SecurityEvent = Literal[
    "api_key_created",
    "api_key_revoked",
    "webhook_url_changed",
    "webhook_secret_rotated",
    "webhook_disabled",
]

#: Cap on recipients per notice. An account with more operators than this is
#: not a case we have; the bound is here so one notice can never become a
#: send loop of unbounded length.
_MAX_RECIPIENTS: Final = 20


async def notify_security(
    db: AsyncSession, *, merchant_id: str, event: SecurityEvent, detail: str = ""
) -> None:
    """Mail every operator on an account that ``event`` happened.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose operators to tell.
        event: One of :data:`SecurityEvent`.
        detail: A short identifier for the thing that changed — a key id, a
            webhook host. Shown so a reader can tell "the key I just made"
            from "a key I did not". Never a secret, and never an address a
            person arrives from.
    """
    users = (
        (
            await db.execute(
                select(MerchantUser)
                .where(MerchantUser.merchant_id == merchant_id)
                .where(MerchantUser.email_confirmed_at.is_not(None))
                .limit(_MAX_RECIPIENTS)
            )
        )
        .scalars()
        .all()
    )
    content = merchant_security_email(event=event, detail=detail)
    for user in users:
        try:
            await send_email(
                to=user.email, subject=content.subject, html=content.html, text=content.text
            )
        except EmailSendError:
            log.exception("merchant.cabinet.security_mail_failed", user_id=user.id, event=event)


__all__ = ["SecurityEvent", "notify_security"]
