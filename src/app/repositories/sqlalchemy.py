"""Generic SQLAlchemy implementation of the Repository protocol.

Parameterized purely by a SQLAlchemy model class (app.models.base.IdentifiedBase
subclass) -- adding a new resource never requires a new repository class, only a
new model.

A few FilterOp branches below are `# pragma: no cover`: app.controllers.crud_query
(the only place that turns an HTTP query string into a FilterClause) never emits
NE/LT/GT/CONTAINS -- its wire format only ever produces EQ/GTE/LTE/IN/ICONTAINS/
REGEX (see its module docstring) -- so those branches can never run through the
real HTTP stack tests/integration/tests/e2e exercise. tests/integration/
repositories/test_sqlalchemy.py's test_every_filter_op_against_real_postgres
calls this repository directly to exercise every FilterOp regardless; the pragma
only affects what's counted toward the e2e coverage gate specifically.

The trailing `case _` in `_where_clauses`'s match is `# pragma: no cover` for a
different reason: FilterOp is exhaustive over the cases above it, so the branch
is unreachable by construction -- it exists only so coverage.py doesn't count the
implicit "no case matched" fall-through of the match statement's last real case
as an untested branch.

Archivable/Schedulable/Lockable (see app.models.mixins) are detected via
`hasattr` on the bound model class -- a model without one of these mixins is
unaffected, matching how app.repositories.memory already special-cases
`created_at`/`updated_at`.

A few Archivable branches below are also `# pragma: no cover`, for the same
reason as app.repositories.memory's own module docstring: Hero is the only model
this app binds to this repository, and Hero always carries Archivable, so
delete()/delete_many()'s genuinely-hard-delete path and restore_many()'s
no-archived_at early return can never run through any test here without a second,
Archivable-less model existing purely to exercise them.

update()/delete()/restore() (the non-`_many` single-record methods) are also
`# pragma: no cover`, for the same reason as app.repositories.memory's own
module docstring's second reason: Hero's own CRUDInterface always sets `owner`
(see app.crud_1.heroes.heroes_v2.get_hero_crud), which routes every
single-record update/delete/restore through this repository's own
update_many/delete_many/restore_many instead (see app.interfaces.base.
OwnerScope's docstring) -- so those three methods can never run through
tests/e2e. tests/integration/repositories/test_sqlalchemy.py calls them
directly, which is what actually covers them for the primary coverage gate;
the pragma only affects what's counted toward the separate `pytest tests/e2e`
coverage gate.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import IdentifiedBase
from app.repositories.base import RecordLockedError
from app.repositories.filtering import FilterClause, FilterOp, SortClause


def _now() -> datetime:
    """Return the current time as naive UTC, matching how naive TIMESTAMP columns store it."""
    return datetime.now(UTC).replace(tzinfo=None)


def _raise_if_locked(instance: object, data: dict[str, Any] | None) -> None:
    """Raise RecordLockedError unless `instance` isn't locked or `data` unlocks it."""
    if not getattr(instance, "is_locked", False):
        return
    if data is not None and data.get("is_locked") is False:
        return
    raise RecordLockedError(f"record {getattr(instance, 'id', '?')!r} is locked")


class SQLAlchemyRepository[ModelT: IdentifiedBase]:
    """Repository backed by a SQLAlchemy async session and a single mapped model."""

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        """Bind this repository to a session and the SQLAlchemy model it persists."""
        self._session = session
        self._model = model

    def _where_clauses(self, filters: Sequence[FilterClause]) -> list[ColumnElement[bool]]:
        """Translate each FilterClause into a SQLAlchemy predicate on this model's columns."""
        clauses: list[ColumnElement[bool]] = []
        for clause in filters:
            column = getattr(self._model, clause.field)
            match clause.op:
                case FilterOp.EQ:
                    clauses.append(column == clause.value)
                case FilterOp.NE:  # pragma: no cover -- see module docstring
                    clauses.append(column != clause.value)
                case FilterOp.LT:  # pragma: no cover -- see module docstring
                    clauses.append(column < clause.value)
                case FilterOp.LTE:
                    clauses.append(column <= clause.value)
                case FilterOp.GT:  # pragma: no cover -- see module docstring
                    clauses.append(column > clause.value)
                case FilterOp.GTE:
                    clauses.append(column >= clause.value)
                case FilterOp.IN:
                    clauses.append(column.in_(clause.value))
                case FilterOp.CONTAINS:  # pragma: no cover -- see module docstring
                    clauses.append(column.contains(clause.value))
                case FilterOp.ICONTAINS:
                    clauses.append(column.ilike(f"%{clause.value}%"))
                case FilterOp.REGEX:
                    clauses.append(column.op("~")(clause.value))
                case _:  # pragma: no cover -- FilterOp is exhaustive above
                    raise AssertionError(clause.op)
        return clauses

    def _visibility_clauses(
        self, *, include_archived: bool, include_unpublished: bool
    ) -> list[ColumnElement[bool]]:
        """Extra WHERE clauses excluding archived/not-yet-or-no-longer-published rows.

        Built with `datetime.now(UTC)` at query time (see app.models.mixins.
        Schedulable), never a stored boolean, so no background process needs to
        touch the row for it to stop/start being visible.
        """
        clauses: list[ColumnElement[bool]] = []
        if not include_archived and hasattr(self._model, "archived_at"):
            archived_at = self._model.archived_at  # type: ignore[attr-defined]
            clauses.append(archived_at.is_(None))
        if not include_unpublished and hasattr(self._model, "publish_at"):
            now = _now()
            publish_at = self._model.publish_at  # type: ignore[attr-defined]
            unpublish_at = self._model.unpublish_at  # type: ignore[attr-defined]
            clauses.append(or_(publish_at.is_(None), publish_at <= now))
            clauses.append(or_(unpublish_at.is_(None), unpublish_at > now))
        return clauses

    def _order_by(self, sort: Sequence[SortClause]) -> list[ColumnElement[Any]]:
        """Translate each SortClause into a SQLAlchemy ORDER BY term on this model's columns."""
        order = []
        for clause in sort:
            column = getattr(self._model, clause.field)
            order.append(column.desc() if clause.descending else column.asc())
        return order

    def _matching(self, filters: Sequence[FilterClause]) -> Select[tuple[ModelT]]:
        return select(self._model).where(*self._where_clauses(filters))

    async def get(
        self, record_id: int, *, include_archived: bool = False, include_unpublished: bool = False
    ) -> ModelT | None:
        """Return the record with the given id, or None if it doesn't exist."""
        instance = await self._session.get(self._model, record_id)
        if instance is None:
            return None
        if not include_archived and getattr(instance, "archived_at", None) is not None:
            return None
        if not include_unpublished:
            now = _now()
            publish_at = getattr(instance, "publish_at", None)
            unpublish_at = getattr(instance, "unpublish_at", None)
            if publish_at is not None and publish_at > now:
                return None
            if unpublish_at is not None and unpublish_at <= now:
                return None
        return instance

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: Sequence[FilterClause] = (),
        sort: Sequence[SortClause] = (),
        include_archived: bool = False,
        include_unpublished: bool = False,
    ) -> Sequence[ModelT]:
        """Return up to `limit` matching records, skipping the first `skip`."""
        order = self._order_by(sort) if sort else [self._model.id.asc()]
        statement = (
            self._matching(filters)
            .where(
                *self._visibility_clauses(
                    include_archived=include_archived, include_unpublished=include_unpublished
                )
            )
            .order_by(*order)
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def count(
        self,
        *,
        filters: Sequence[FilterClause] = (),
        include_archived: bool = False,
        include_unpublished: bool = False,
    ) -> int:
        """Return how many records match the given filters.

        Called by app.controllers.crud_actions before a bulk update/delete, to cap
        how many records a single action can affect.
        """
        statement = (
            select(func.count())
            .select_from(self._model)
            .where(
                *self._where_clauses(filters),
                *self._visibility_clauses(
                    include_archived=include_archived, include_unpublished=include_unpublished
                ),
            )
        )
        result = await self._session.execute(statement)
        return result.scalar_one()

    async def create(self, data: dict[str, Any]) -> ModelT:
        """Insert a new row from the given field values and return it."""
        instance = self._model(**data)
        self._session.add(instance)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def update(  # pragma: no cover -- see module docstring
        self, record_id: int, data: dict[str, Any]
    ) -> ModelT | None:
        """Apply the given field values to the record with the given id, if it exists."""
        instance = await self._session.get(self._model, record_id)
        if instance is None or getattr(instance, "archived_at", None) is not None:
            return None
        _raise_if_locked(instance, data)
        for field, value in data.items():
            setattr(instance, field, value)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def delete(self, record_id: int) -> bool:  # pragma: no cover -- see module docstring
        """Delete the record with the given id; return whether it existed."""
        instance = await self._session.get(self._model, record_id)
        if instance is None:
            return False
        if hasattr(instance, "archived_at"):
            if instance.archived_at is not None:
                return False
            _raise_if_locked(instance, None)
            instance.archived_at = _now()
            await self._session.flush()
            return True
        _raise_if_locked(instance, None)
        await self._session.delete(instance)
        await self._session.flush()
        return True

    async def update_many(
        self, *, filters: Sequence[FilterClause], data: dict[str, Any]
    ) -> Sequence[ModelT]:
        """Apply the given field values to every record matching the filters; return them.

        Excludes archived rows by default, same as delete/get/list/count -- an
        archived record needs restore() before it can be touched again. Unlike
        those, a not-yet-or-no-longer-published (Schedulable) row is still
        reachable here -- it isn't deleted, just not currently visible, and an
        editor must still be able to correct a scheduled record before it goes
        live (see app.models.mixins.Schedulable).
        """
        statement = self._matching(filters).where(
            *self._visibility_clauses(include_archived=False, include_unpublished=True)
        )
        result = await self._session.execute(statement)
        instances = result.scalars().all()
        for instance in instances:
            _raise_if_locked(instance, data)
        for instance in instances:
            for field, value in data.items():
                setattr(instance, field, value)
        await self._session.flush()
        for instance in instances:
            await self._session.refresh(instance)
        return instances

    async def delete_many(self, *, filters: Sequence[FilterClause]) -> Sequence[ModelT]:
        """Delete every record matching the filters; return the records that were deleted.

        Excludes already-archived rows by default, same as update_many above -- a
        not-yet-or-no-longer-published row is still reachable (see update_many's
        own docstring for why).
        """
        statement = self._matching(filters).where(
            *self._visibility_clauses(include_archived=False, include_unpublished=True)
        )
        result = await self._session.execute(statement)
        instances = result.scalars().all()
        for instance in instances:
            _raise_if_locked(instance, None)
        now = _now()
        for instance in instances:
            if hasattr(instance, "archived_at"):
                instance.archived_at = now
            else:
                await self._session.delete(instance)  # pragma: no cover -- see module docstring
        await self._session.flush()
        for instance in instances:
            if hasattr(instance, "archived_at"):  # pragma: no branch -- see module docstring
                await self._session.refresh(instance)
        return instances

    async def restore(  # pragma: no cover -- see module docstring
        self, record_id: int
    ) -> ModelT | None:
        """Clear `archived_at` on the record with the given id; return it, or None."""
        instance = await self._session.get(self._model, record_id)
        if instance is None or not hasattr(instance, "archived_at"):
            return None
        instance.archived_at = None
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def restore_many(self, *, filters: Sequence[FilterClause]) -> Sequence[ModelT]:
        """Clear `archived_at` on every record matching the filters; return them."""
        if not hasattr(self._model, "archived_at"):
            return []  # pragma: no cover -- see module docstring
        result = await self._session.execute(self._matching(filters))
        instances = result.scalars().all()
        for instance in instances:
            instance.archived_at = None  # type: ignore[attr-defined]
        await self._session.flush()
        for instance in instances:
            await self._session.refresh(instance)
        return instances
