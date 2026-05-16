"""Public surface of the ``users`` module.

Cross-module callers must import only from here. Internals (models, service, schemas)
are implementation details.
"""

from yupay.modules.users.schemas import UserOut
from yupay.modules.users.service import (
    get_user_by_id,
    get_user_by_telegram_id,
    upsert_user_by_telegram,
)

__all__ = [
    "UserOut",
    "get_user_by_id",
    "get_user_by_telegram_id",
    "upsert_user_by_telegram",
]
