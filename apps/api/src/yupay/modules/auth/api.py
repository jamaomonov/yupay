"""Public surface of the ``auth`` module.

Cross-module callers must import only from here. The HTTP router is mounted by
:mod:`yupay.api.v1` via :data:`router`.
"""

from yupay.modules.auth.routes import router
from yupay.modules.auth.schemas import (
    GuestIn,
    GuestTokenOut,
    MeOut,
    TelegramInitDataIn,
    TelegramWidgetIn,
    TokensOut,
)
from yupay.modules.auth.service import (
    GuestToken,
    SessionTokens,
    current_user,
    guest_checkout,
    logout,
    refresh_session,
    telegram_init_data_login,
    telegram_widget_login,
)

__all__ = [
    "GuestIn",
    "GuestToken",
    "GuestTokenOut",
    "MeOut",
    "SessionTokens",
    "TelegramInitDataIn",
    "TelegramWidgetIn",
    "TokensOut",
    "current_user",
    "guest_checkout",
    "logout",
    "refresh_session",
    "router",
    "telegram_init_data_login",
    "telegram_widget_login",
]
