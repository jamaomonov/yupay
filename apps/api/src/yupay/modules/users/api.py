"""Public surface of the ``users`` module.

Cross-module callers must import only from here. Internals (models, service, schemas)
are implementation details.
"""

from yupay.modules.users.routes import admin_router, router
from yupay.modules.users.schemas import (
    DisplayCurrencyLiteral,
    TelegramLinkOut,
    UpdateMeIn,
    UserAdminListOut,
    UserAdminOut,
    UserOut,
    UserRolesIn,
)
from yupay.modules.users.service import (
    get_user_admin,
    get_user_by_id,
    get_user_by_telegram_id,
    list_users_admin,
    set_user_roles,
    update_me,
    upsert_user_by_telegram,
)

__all__ = [
    "DisplayCurrencyLiteral",
    "TelegramLinkOut",
    "UpdateMeIn",
    "UserAdminListOut",
    "UserAdminOut",
    "UserOut",
    "UserRolesIn",
    "admin_router",
    "get_user_admin",
    "get_user_by_id",
    "get_user_by_telegram_id",
    "list_users_admin",
    "router",
    "set_user_roles",
    "update_me",
    "upsert_user_by_telegram",
]
