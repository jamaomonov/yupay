"""Async SQLAlchemy engine, session factory, and shared declarative metadata.

Modules define their tables on the shared :data:`metadata` so Alembic can autogenerate
migrations across the whole app. Each module imports :data:`Base` from here and uses
``MappedAsDataclass``/``DeclarativeBase`` for ergonomic model definitions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from yupay.core.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    # WARNING: because this template contains %(constraint_name)s, SQLAlchemy
    # re-templates it even for a CheckConstraint that already has an explicit
    # `name=`. Writing `name="ck_table_x"` therefore ships as
    # `ck_table_ck_table_x`, not `ck_table_x` — pass the bare suffix
    # (`name="x"`) and let this convention supply the `ck_table_` prefix.
    # `affiliate` and `orders` already shipped double-prefixed names this way
    # (`ck_orders_ck_orders_actor_exclusive` is live in production) — don't
    # "fix" an old name to match the new pattern without a migration.
    # The same re-templating fires inside alembic migrations: env.py hands
    # this metadata to alembic as `target_metadata`, and both
    # `op.create_check_constraint` and `op.drop_constraint` build their
    # constraint objects on it. A migration that refers to an EXISTING
    # constraint by its literal name must therefore wrap the name in
    # `sqlalchemy.sql.elements.conv()`, or it gets prefixed once more on the
    # way out (a drop of the double-prefixed name above would look for a
    # triple-prefixed one). Migration 0066 does this for both its drop and
    # its downgrade re-add.
    # TWO patterns are therefore valid, and which one you need depends on how
    # the constraint was BORN. A constraint created through the re-templating
    # path (full explicit `name="ck_table_x"`, shipped double-prefixed — e.g.
    # 0009's wallet CHECKs) is dropped/re-added with the same BARE full name,
    # which re-templates back into the live double-prefixed one (0018, 0056,
    # 0067). A constraint you must address by its LITERAL live name needs
    # `conv()` so it is NOT re-templated (0066). To pick: look at what `\d`
    # shows on a real database and at the migration that created the name.
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for all ORM models.

    Subclasses live inside each module under ``yupay.modules.<name>.models``. The
    ``AsyncAttrs`` mixin exposes ``model.awaitable_attrs.<rel>`` so async code can
    explicitly trigger lazy loads without falling out of the greenlet context.
    """

    metadata = metadata


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the lazily-initialised async engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=10,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-initialised async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a transactional session per request."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine on application shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
