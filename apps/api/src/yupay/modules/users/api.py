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
    UserAdminSort,
    UserOut,
    UserRolesIn,
    UserWalletBalanceOut,
)
from yupay.modules.users.service import (
    AdminUserListPage,
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
    "AdminUserListPage",
    "BanUserIn",
    "DisplayCurrencyLiteral",
    "TelegramLinkOut",
    "UpdateMeIn",
    "UserAdminListOut",
    "UserAdminOut",
    "UserAdminSort",
    "UserOut",
    "UserRolesIn",
    "UserWalletBalanceOut",
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
