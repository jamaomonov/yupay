"""Public surface of the ``users`` module.

Cross-module callers must import only from here. Internals (models, service, schemas)
are implementation details.
"""

from yupay.modules.users.routes import admin_router, router
from yupay.modules.users.schemas import (
    BanUserIn,
    DisplayCurrencyLiteral,
    TelegramLinkOut,
    UpdateMeIn,
    UserAdminListOut,
    UserAdminOut,
    UserOut,
    UserRolesIn,
)
from yupay.modules.users.service import (
    ban_user,
    get_user_admin,
    get_user_by_id,
    get_user_by_telegram_id,
    is_email_banned,
    list_users_admin,
    set_user_roles,
    unban_user,
    update_me,
    upsert_user_by_telegram,
)

__all__ = [
    "BanUserIn",
    "DisplayCurrencyLiteral",
    "TelegramLinkOut",
    "UpdateMeIn",
    "UserAdminListOut",
    "UserAdminOut",
    "UserOut",
    "UserRolesIn",
    "admin_router",
    "ban_user",
    "get_user_admin",
    "get_user_by_id",
    "get_user_by_telegram_id",
    "is_email_banned",
    "list_users_admin",
    "router",
    "set_user_roles",
    "unban_user",
    "update_me",
    "upsert_user_by_telegram",
]
