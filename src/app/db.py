"""The app's async SQLAlchemy engine and session factory, built from `Settings`."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings

# NullPool: an asyncpg connection is tied to the event loop it was opened on, and
# pooling would hand one from a closed-out loop to a new one -- fine for the app's
# own single long-lived event loop, but tests/integration mixes pytest-asyncio's
# loop with TestClient's own background-thread loop, which pooling can't survive
# ("cannot perform operation: another operation is in progress"). A fresh
# connection per checkout sidesteps that everywhere, at the cost of connection
# reuse -- acceptable for this template's traffic; front it with PgBouncer instead
# of re-enabling pooling here if that ever matters.
engine: AsyncEngine = create_async_engine(get_settings().database_url, poolclass=NullPool)
session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)
