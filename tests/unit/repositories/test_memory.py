"""Unit test: InMemoryRepository's filter/sort/bulk logic, one case per FilterOp.

Uses the Hero model directly (not mocked) since InMemoryRepository is generic over
any IdentifiedBase subclass and Hero is already the example resource in this repo.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.hero import Hero
from app.repositories import memory
from app.repositories.base import RecordLockedError
from app.repositories.filtering import FilterClause, FilterOp, SortClause
from app.repositories.memory import InMemoryRepository


@pytest.fixture
async def repository() -> InMemoryRepository[Hero]:
    """Return a fresh InMemoryRepository seeded with three heroes."""
    repo = InMemoryRepository(Hero)
    await repo.create({"name": "Batman", "powers": ["Detective skills"]})
    await repo.create({"name": "Batgirl", "powers": ["Detective skills"]})
    await repo.create({"name": "Superman", "powers": ["Flight"]})
    return repo


async def test_filter_eq(repository: InMemoryRepository[Hero]) -> None:
    """EQ matches only records with the exact field value."""
    matching = await repository.list(filters=[FilterClause("name", FilterOp.EQ, "Batman")])
    assert [hero.name for hero in matching] == ["Batman"]


async def test_filter_ne(repository: InMemoryRepository[Hero]) -> None:
    """NE matches every record except those with the exact field value."""
    matching = await repository.list(filters=[FilterClause("name", FilterOp.NE, "Batman")])
    assert {hero.name for hero in matching} == {"Batgirl", "Superman"}


async def test_filter_lt_lte_gt_gte(repository: InMemoryRepository[Hero]) -> None:
    """LT/LTE/GT/GTE compare against the given value."""
    heroes = await repository.list()
    ids = sorted(hero.id for hero in heroes)
    lt = await repository.list(filters=[FilterClause("id", FilterOp.LT, ids[1])])
    assert [hero.id for hero in lt] == [ids[0]]
    lte = await repository.list(filters=[FilterClause("id", FilterOp.LTE, ids[1])])
    assert sorted(hero.id for hero in lte) == ids[:2]
    gt = await repository.list(filters=[FilterClause("id", FilterOp.GT, ids[1])])
    assert [hero.id for hero in gt] == [ids[2]]
    gte = await repository.list(filters=[FilterClause("id", FilterOp.GTE, ids[1])])
    assert sorted(hero.id for hero in gte) == ids[1:]


async def test_filter_in(repository: InMemoryRepository[Hero]) -> None:
    """IN matches records whose field value is a member of the given collection."""
    matching = await repository.list(
        filters=[FilterClause("name", FilterOp.IN, ["Batman", "Superman"])]
    )
    assert {hero.name for hero in matching} == {"Batman", "Superman"}


async def test_filter_contains(repository: InMemoryRepository[Hero]) -> None:
    """CONTAINS matches a case-sensitive substring."""
    matching = await repository.list(filters=[FilterClause("name", FilterOp.CONTAINS, "Bat")])
    assert {hero.name for hero in matching} == {"Batman", "Batgirl"}
    assert await repository.list(filters=[FilterClause("name", FilterOp.CONTAINS, "bat")]) == []


async def test_filter_icontains(repository: InMemoryRepository[Hero]) -> None:
    """ICONTAINS matches a case-insensitive substring."""
    matching = await repository.list(filters=[FilterClause("name", FilterOp.ICONTAINS, "bat")])
    assert {hero.name for hero in matching} == {"Batman", "Batgirl"}


async def test_filter_regex(repository: InMemoryRepository[Hero]) -> None:
    """REGEX matches records whose field value matches the given pattern."""
    matching = await repository.list(filters=[FilterClause("name", FilterOp.REGEX, "^Bat.*")])
    assert {hero.name for hero in matching} == {"Batman", "Batgirl"}


def test_regex_alarm_handler_raises_regex_timeout_error() -> None:
    """The SIGALRM handler backing _regex_matches's timeout raises _RegexTimeoutError.

    Exercised directly (rather than only via a real catastrophic-backtracking match)
    so this unit test stays fast and deterministic.
    """
    with pytest.raises(memory._RegexTimeoutError):
        memory._on_regex_alarm(0, None)


def test_regex_matches_returns_false_and_logs_on_timeout(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A pattern whose match exceeds the budget is treated as "no match", not a hang.

    Uses a genuinely catastrophic-backtracking pattern ("(a+)+$" against a string with
    no trailing match) against a very short budget, so this actually exercises the
    SIGALRM-triggered abort path rather than just the happy path.
    """
    monkeypatch.setattr(memory, "_REGEX_TIMEOUT_SECONDS", 0.05)
    with caplog.at_level("WARNING"):
        assert memory._regex_matches("(a+)+$", "a" * 30 + "!") is False
    assert "exceeded" in caplog.text


async def test_filter_regex_rejects_unknown_field(repository: InMemoryRepository[Hero]) -> None:
    """A filter/sort field that isn't a real mapped column raises, not an AttributeError."""
    with pytest.raises(ValueError, match="not a filterable/sortable column"):
        await repository.list(filters=[FilterClause("not_a_real_field", FilterOp.EQ, "x")])


async def test_sort_ascending_and_descending(repository: InMemoryRepository[Hero]) -> None:
    """Sorting orders by field value, reversed when descending is set."""
    ascending = await repository.list(sort=[SortClause("name")])
    assert [hero.name for hero in ascending] == ["Batgirl", "Batman", "Superman"]
    descending = await repository.list(sort=[SortClause("name", descending=True)])
    assert [hero.name for hero in descending] == ["Superman", "Batman", "Batgirl"]


async def test_count_matches_filters(repository: InMemoryRepository[Hero]) -> None:
    """count() reports how many records match the given filters."""
    assert await repository.count() == 3
    assert await repository.count(filters=[FilterClause("name", FilterOp.ICONTAINS, "bat")]) == 2


async def test_get_update_and_delete_by_id(repository: InMemoryRepository[Hero]) -> None:
    """get()/update()/delete() (single-record) round-trip by id.

    Exercised directly here since Hero's own real HTTP routes no longer call these
    for update/delete -- app.crud_1.heroes.heroes_v2.get_hero_crud always sets an
    OwnerScope, which routes CRUDInterface.update/delete through update_many/
    delete_many instead (see app.interfaces.base.OwnerScope's docstring).
    """
    heroes = await repository.list()
    batman = next(hero for hero in heroes if hero.name == "Batman")

    fetched = await repository.get(batman.id)
    assert fetched is not None
    assert fetched.name == "Batman"

    updated = await repository.update(batman.id, {"powers": ["Martial arts"]})
    assert updated is not None
    assert updated.powers == ["Martial arts"]

    assert await repository.delete(batman.id) is True
    assert await repository.get(batman.id) is None
    assert await repository.delete(batman.id) is False
    assert await repository.update(batman.id, {"powers": ["N/A"]}) is None


async def test_update_many_applies_to_every_match(repository: InMemoryRepository[Hero]) -> None:
    """update_many() applies the update to every record matching the filters."""
    updated = await repository.update_many(
        filters=[FilterClause("name", FilterOp.ICONTAINS, "bat")],
        data={"powers": ["Martial arts"]},
    )
    assert {hero.name for hero in updated} == {"Batman", "Batgirl"}
    assert all(hero.powers == ["Martial arts"] for hero in updated)
    assert await repository.count() == 3


async def test_delete_many_removes_every_match(repository: InMemoryRepository[Hero]) -> None:
    """delete_many() removes every record matching the filters and returns them."""
    deleted = await repository.delete_many(
        filters=[FilterClause("name", FilterOp.ICONTAINS, "bat")]
    )
    assert {hero.name for hero in deleted} == {"Batman", "Batgirl"}
    assert await repository.count() == 1


async def test_lock_blocks_update_and_delete_except_the_unlocking_update(
    repository: InMemoryRepository[Hero],
) -> None:
    """A locked Hero refuses update/delete (single and bulk), except an update whose
    data is exactly `{"is_locked": False}` -- see
    app.repositories.base.RecordLockedError and app.models.mixins.Lockable.
    """
    locked = await repository.create(
        {"name": "Locked Hero", "powers": ["Immovable"], "is_locked": True}
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


async def test_schedulable_visibility_excludes_future_publish_and_past_unpublish(
    repository: InMemoryRepository[Hero],
) -> None:
    """get()/list() exclude a not-yet-published or no-longer-published Hero by default,
    and `include_unpublished=True` reaches it -- see app.models.mixins.Schedulable.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    not_yet_published = await repository.create(
        {"name": "Not Yet Published", "powers": ["A"], "publish_at": now + timedelta(days=1)}
    )
    no_longer_published = await repository.create(
        {"name": "No Longer Published", "powers": ["A"], "unpublish_at": now - timedelta(days=1)}
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


async def test_restore_missing_returns_none(repository: InMemoryRepository[Hero]) -> None:
    """restore() returns None for an id that doesn't exist."""
    assert await repository.restore(999) is None


async def test_restore_many_via_filters(repository: InMemoryRepository[Hero]) -> None:
    """restore_many() clears archived_at on every matching row."""
    heroes = await repository.list()
    batman = next(hero for hero in heroes if hero.name == "Batman")
    batgirl = next(hero for hero in heroes if hero.name == "Batgirl")
    assert await repository.delete(batman.id) is True
    assert await repository.delete(batgirl.id) is True

    name_filter = [FilterClause("name", FilterOp.ICONTAINS, "bat")]
    restored = await repository.restore_many(filters=name_filter)
    assert {hero.id for hero in restored} == {batman.id, batgirl.id}
    assert all(hero.archived_at is None for hero in restored)
    assert await repository.get(batman.id) is not None


async def test_delete_missing_returns_false(repository: InMemoryRepository[Hero]) -> None:
    """delete() returns False for an id that was never created, not just an archived one."""
    assert await repository.delete(999) is False


async def test_restore_clears_archived_at(repository: InMemoryRepository[Hero]) -> None:
    """restore() (single-record, not restore_many) clears archived_at and returns the record."""
    heroes = await repository.list()
    batman = next(hero for hero in heroes if hero.name == "Batman")
    assert await repository.delete(batman.id) is True

    restored = await repository.restore(batman.id)
    assert restored is not None
    assert restored.archived_at is None
    assert await repository.get(batman.id) is not None
