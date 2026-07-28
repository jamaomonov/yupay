"""Alembic environment configuration for YuPay.

Uses the same async SQLAlchemy URL as the application via ``yupay.core.config``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from yupay.core.config import get_settings
from yupay.core.db import metadata

# Import all module models so Alembic's metadata sees every table when autogenerating
# migrations. New modules MUST add their imports here.
from yupay.core import idempotency as _idempotency_models  # noqa: F401
from yupay.modules.auth import models as _auth_models  # noqa: F401
from yupay.modules.catalog import models as _catalog_models  # noqa: F401
from yupay.modules.fulfillment import models as _fulfillment_models  # noqa: F401
from yupay.modules.fx import models as _fx_models  # noqa: F401
from yupay.modules.integrations import models as _integrations_models  # noqa: F401
from yupay.modules.inventory import models as _inventory_models  # noqa: F401
from yupay.modules.orders import models as _orders_models  # noqa: F401
from yupay.modules.payments import models as _payments_models  # noqa: F401
from yupay.modules.reviews import models as _reviews_models  # noqa: F401
from yupay.modules.sourcing import models as _sourcing_models  # noqa: F401
from yupay.modules.users import models as _users_models  # noqa: F401
from yupay.modules.wallet import models as _wallet_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode against a URL, without an Engine."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    """Run migrations against a live connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
