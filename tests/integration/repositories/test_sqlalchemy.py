"""Integration test: SQLAlchemyRepository against the real Postgres stack service."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.base import async_session_factory
from app.models.hero import Hero
from app.repositories.base import RecordLockedError
from app.repositories.filtering import FilterClause, FilterOp, SortClause
from app.repositories.sqlalchemy import SQLAlchemyRepository


async def test_crud_roundtrip_against_real_postgres() -> None:
    """create/get/list/update/delete all round-trip through a real Postgres session.

    Runs inside one uncommitted session so nothing is left behind afterwards --
    closing the session without committing rolls back everything written here.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)

        created = await repository.create(
            {"name": "Iron Man", "powers": ["Powered armor"], "owner_id": "tester"}
        )
        assert created.id is not None

        fetched = await repository.get(created.id)
        assert fetched is not None
        assert fetched.name == "Iron Man"

        heroes = await repository.list()
        assert any(hero.id == created.id for hero in heroes)

        updated = await repository.update(created.id, {"powers": ["Repulsor blasts"]})
        assert updated is not None
        assert updated.powers == ["Repulsor blasts"]

        # Hero is Archivable (see app.models.mixins): delete() marks archived_at
        # rather than removing the row, so get() excludes it by default but the
        # row itself is still there -- an archived row is excluded from normal
        # reads, so a second delete() and a plain update() both act as if the
        # row is gone (False/None), same as a genuine hard delete would from the
        # caller's point of view. Only restore()/get(include_archived=True)
        # reach it.
        assert await repository.delete(created.id) is True
        assert await repository.get(created.id) is None
        assert await repository.get(created.id, include_archived=True) is not None
        assert await repository.delete(created.id) is False
        assert await repository.update(created.id, {"powers": ["N/A"]}) is None
        restored = await repository.restore(created.id)
        assert restored is not None
        assert restored.archived_at is None
        assert await repository.get(created.id) is not None


async def test_filter_sort_and_bulk_actions_against_real_postgres() -> None:
    """list/count/update_many/delete_many honor FilterClause/SortClause against Postgres.

    Runs inside one uncommitted session, same isolation as the roundtrip test above.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)

        batman = await repository.create(
            {"name": "Batman", "powers": ["Detective skills"], "owner_id": "tester"}
        )
        batgirl = await repository.create(
            {"name": "Batgirl", "powers": ["Detective skills"], "owner_id": "tester"}
        )
        superman = await repository.create(
            {"name": "Superman", "powers": ["Flight"], "owner_id": "tester"}
        )

        name_filter = [FilterClause("name", FilterOp.ICONTAINS, "bat")]
        assert await repository.count(filters=name_filter) == 2

        matching = await repository.list(filters=name_filter, sort=[SortClause("name")])
        assert [hero.name for hero in matching] == ["Batgirl", "Batman"]

        id_filter = [FilterClause("id", FilterOp.IN, [batman.id, batgirl.id, superman.id])]
        descending = await repository.list(
            filters=id_filter, sort=[SortClause("name", descending=True)]
        )
        assert [hero.name for hero in descending] == ["Superman", "Batman", "Batgirl"]

        updated = await repository.update_many(
            filters=name_filter, data={"powers": ["Martial arts"]}
        )
        assert {hero.id for hero in updated} == {batman.id, batgirl.id}
        assert all(hero.powers == ["Martial arts"] for hero in updated)

        deleted = await repository.delete_many(filters=name_filter)
        assert {hero.id for hero in deleted} == {batman.id, batgirl.id}
        assert await repository.get(batman.id) is None
        assert await repository.get(superman.id) is not None


async def test_every_filter_op_against_real_postgres() -> None:
    """Each FilterOp maps to a working predicate in the real Postgres backend.

    Runs inside one uncommitted session, same isolation as the tests above.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)
        low = await repository.create(
            {"name": "FilterOp Low", "powers": ["A"], "owner_id": "tester"}
        )
        high = await repository.create(
            {"name": "FilterOp High", "powers": ["A"], "owner_id": "tester"}
        )
        ids = [low.id, high.id]

        def by(op: FilterOp, value: object) -> list[FilterClause]:
            return [FilterClause("id", FilterOp.IN, ids), FilterClause("id", op, value)]

        assert [h.id for h in await repository.list(filters=by(FilterOp.EQ, low.id))] == [low.id]
        assert {h.id for h in await repository.list(filters=by(FilterOp.NE, low.id))} == {high.id}
        assert [h.id for h in await repository.list(filters=by(FilterOp.LT, high.id))] == [low.id]
        assert {h.id for h in await repository.list(filters=by(FilterOp.LTE, high.id))} == {
            low.id,
            high.id,
        }
        assert [h.id for h in await repository.list(filters=by(FilterOp.GT, low.id))] == [high.id]
        assert {h.id for h in await repository.list(filters=by(FilterOp.GTE, low.id))} == {
            low.id,
            high.id,
        }
        assert {
            h.id
            for h in await repository.list(
                filters=[
                    FilterClause("name", FilterOp.CONTAINS, "FilterOp"),
                    FilterClause("id", FilterOp.IN, ids),
                ]
            )
        } == {low.id, high.id}
        assert [
            h.id
            for h in await repository.list(
                filters=[FilterClause("name", FilterOp.REGEX, "^FilterOp Low$")]
            )
        ] == [low.id]
        assert [
            h.id
            for h in await repository.list(
                filters=[
                    FilterClause("name", FilterOp.REGEX, "^FilterOp"),
                    FilterClause("id", FilterOp.IN, ids),
                ]
            )
        ] == ids


async def test_lock_blocks_update_and_delete_except_the_unlocking_update() -> None:
    """A locked Hero refuses update/delete (single and bulk), except an update whose
    data is exactly `{"is_locked": False}` -- see
    app.repositories.base.RecordLockedError and
    app.repositories.sqlalchemy._raise_if_locked's own docstring.

    Runs inside one uncommitted session, same isolation as the tests above.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)
        locked = await repository.create(
            {
                "name": "Locked Hero",
                "powers": ["Immovable"],
                "owner_id": "tester",
                "is_locked": True,
            }
        )

        with pytest.raises(RecordLockedError):
            await repository.update(locked.id, {"powers": ["Should not apply"]})
        with pytest.raises(RecordLockedError):
            await repository.delete(locked.id)

        id_filter = [FilterClause("id", FilterOp.EQ, locked.id)]
        with pytest.raises(RecordLockedError):
            await repository.update_many(filters=id_filter, data={"powers": ["Nope"]})
        with pytest.raises(RecordLockedError):
            await repository.delete_many(filters=id_filter)

        # Unlocking and editing in the same request is refused too -- unlock must be
        # its own request, not a way to slip an edit past the lock.
        with pytest.raises(RecordLockedError):
            await repository.update(locked.id, {"is_locked": False, "powers": ["Should not apply"]})

        unlocked = await repository.update(locked.id, {"is_locked": False})
        assert unlocked is not None
        assert unlocked.is_locked is False

        edited = await repository.update(locked.id, {"powers": ["Freed"]})
        assert edited is not None
        assert edited.powers == ["Freed"]


async def test_schedulable_visibility_excludes_future_publish_and_past_unpublish() -> None:
    """get()/list() exclude a not-yet-published or no-longer-published Hero by default,
    and `include_unpublished=True` reaches it -- see app.models.mixins.Schedulable.

    Runs inside one uncommitted session, same isolation as the tests above.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)
        now = datetime.now(UTC).replace(tzinfo=None)

        not_yet_published = await repository.create(
            {
                "name": "Not Yet Published",
                "powers": ["A"],
                "owner_id": "tester",
                "publish_at": now + timedelta(days=1),
            }
        )
        no_longer_published = await repository.create(
            {
                "name": "No Longer Published",
                "powers": ["A"],
                "owner_id": "tester",
                "unpublish_at": now - timedelta(days=1),
            }
        )

        assert await repository.get(not_yet_published.id) is None
        assert await repository.get(no_longer_published.id) is None
        assert await repository.get(not_yet_published.id, include_unpublished=True) is not None
        assert await repository.get(no_longer_published.id, include_unpublished=True) is not None

        ids = [not_yet_published.id, no_longer_published.id]
        id_filter = [FilterClause("id", FilterOp.IN, ids)]
        assert await repository.list(filters=id_filter) == []
        visible = await repository.list(filters=id_filter, include_unpublished=True)
        assert {hero.id for hero in visible} == set(ids)


async def test_restore_many_via_filters() -> None:
    """restore_many() clears archived_at on every matching row.

    Runs inside one uncommitted session, same isolation as the tests above.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)
        batman = await repository.create(
            {"name": "Restorable Batman", "powers": ["A"], "owner_id": "tester"}
        )
        batgirl = await repository.create(
            {"name": "Restorable Batgirl", "powers": ["A"], "owner_id": "tester"}
        )
        assert await repository.delete(batman.id) is True
        assert await repository.delete(batgirl.id) is True

        name_filter = [FilterClause("name", FilterOp.ICONTAINS, "Restorable")]
        restored = await repository.restore_many(filters=name_filter)
        assert {hero.id for hero in restored} == {batman.id, batgirl.id}
        assert all(hero.archived_at is None for hero in restored)
        assert await repository.get(batman.id) is not None


async def test_delete_missing_returns_false() -> None:
    """delete() returns False for an id that doesn't exist, not just an already-archived one."""
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)
        assert await repository.delete(-1) is False


async def test_restore_single_record_clears_archived_at() -> None:
    """restore() (single-record, not restore_many) clears archived_at and returns the record.

    Runs inside one uncommitted session, same isolation as the tests above.
    """
    async with async_session_factory() as session:
        repository = SQLAlchemyRepository(session, Hero)
        assert await repository.restore(-1) is None

        created = await repository.create(
            {"name": "Restore Single", "powers": ["A"], "owner_id": "tester"}
        )
        assert await repository.delete(created.id) is True

        restored = await repository.restore(created.id)
        assert restored is not None
        assert restored.archived_at is None
        assert await repository.get(created.id) is not None
