"""Integration test: app.maintenance.purge_archived against the real Postgres stack service."""

from datetime import UTC, datetime, timedelta

from app.maintenance import purge_archived
from app.models.hero import Hero
from crud.models.base import async_session_factory
from crud.repositories.sqlalchemy import SQLAlchemyRepository


async def test_purge_archived_deletes_only_rows_past_older_than() -> None:
    """Only archived rows at or before `older_than` are deleted; everything else is untouched.

    Runs inside one uncommitted session, same isolation as tests/integration/repositories/
    test_sqlalchemy.py -- closing the session without committing rolls back everything
    written here.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)

        old_and_archived = await repository.create(
            {"name": "Ancient Hero", "powers": ["Rust"], "owner_id": "tester"}
        )
        recently_archived = await repository.create(
            {"name": "Recent Hero", "powers": ["Rust"], "owner_id": "tester"}
        )
        never_archived = await repository.create(
            {"name": "Active Hero", "powers": ["Rust"], "owner_id": "tester"}
        )

        assert await repository.delete(old_and_archived.id) is True
        assert await repository.delete(recently_archived.id) is True

        now = datetime.now(UTC).replace(tzinfo=None)
        # Backdate old_and_archived's own archived_at directly -- purge_archived only
        # cares about the column value, not when delete() was actually called.
        old_and_archived.archived_at = now - timedelta(days=30)
        await session.flush()

        deleted = await purge_archived(session, older_than=now - timedelta(days=1))
        assert deleted == 1

        assert await session.get(Hero, old_and_archived.id) is None
        assert await session.get(Hero, recently_archived.id) is not None
        assert await session.get(Hero, never_archived.id) is not None
