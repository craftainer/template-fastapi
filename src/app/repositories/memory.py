"""In-memory implementation of the Repository protocol, used when MODE=mock.

Parameterized purely by a SQLAlchemy model class, matching sqlalchemy.py's shape --
adding a new mock-backed resource never requires a new repository class, only a
model. Unlike SQLAlchemyRepository, there is no server to supply `created_at`/
`updated_at` via `server_default`/`onupdate` (see app.models.base.IdentifiedBase),
so this repository sets them itself -- as naive UTC datetimes, matching the naive
`TIMESTAMP` columns Postgres stores them as (both conventionally UTC, per
IdentifiedBase's own docstring), so a datetime filter value (normalized to naive
UTC the same way in app.controllers.crud_query) compares correctly against either
backend.

Archivable/Schedulable/Lockable (see app.models.mixins) are detected via `hasattr`
on a stored instance -- a model without one of these mixins is unaffected, matching
how `created_at`/`updated_at` are already special-cased here.

tests/unit exercises every method below directly; tests/e2e's MODE=mock leg
exercises them too through the real HTTP stack.

A few branches below are `# pragma: no cover`, for two different reasons:

- Hero is the only model this app binds to this repository, and Hero always
  carries Archivable (see app.models.hero) -- delete()/delete_many()'s
  genuinely-hard-delete path (for a model with no `archived_at` at all)
  therefore can never run through any test here without a second,
  Archivable-less model existing purely to exercise it. The plan behind
  app.models.mixins keeps that path so a future non-Archivable resource still
  gets today's hard-delete behavior unchanged (see docs/adrs/0012-soft-delete-
  via-marker-column.md) -- it's real, load-bearing generic code, just not one
  this app's own single example resource can reach.
- Hero's own CRUDInterface always sets `owner` (see app.crud_1.heroes.
  heroes_v2.get_hero_crud), which routes every single-record update/delete/
  restore through this repository's own update_many/delete_many/restore_many
  instead (see app.interfaces.base.OwnerScope's docstring) -- so update()/
  delete()/restore() (the non-`_many` single-record methods) can never run
  through tests/e2e either. tests/unit/repositories/test_memory.py calls them
  directly, which is what actually covers them for the primary (`pytest`, i.e.
  tests/unit + tests/integration) coverage gate; the pragma only affects what's
  counted toward the separate `pytest tests/e2e` coverage gate.
"""

import logging
import re
import signal
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect

from app.models.base import IdentifiedBase
from app.repositories.base import RecordLockedError
from app.repositories.filtering import FilterClause, FilterOp, SortClause

logger = logging.getLogger(__name__)

# A FilterOp.REGEX pattern reaches Python's re.search verbatim -- app.controllers.
# crud_query's own length cap bounds a pattern's *size*, not its worst-case
# backtracking cost (a short pattern like "(a+)+$" is already catastrophic against a
# crafted string). re has no built-in backtracking limit, so this repository (unlike
# SQLAlchemyRepository, which delegates to Postgres's own engine) is directly
# exposed: a pathological match run inline here blocks the whole event loop, not just
# one request. `_REGEX_TIMEOUT_SECONDS` bounds that with a wall-clock alarm --
# relies on running on the main thread of a single-process worker (true for this
# app's asyncio event loop; see app.models.base's NullPool comment for the same
# single-worker assumption elsewhere) -- a runaway match is aborted and treated as
# "no match" rather than hanging the process indefinitely.
_REGEX_TIMEOUT_SECONDS = 1


class _RegexTimeoutError(Exception):
    """Raised internally when a FilterOp.REGEX match exceeds its evaluation budget."""


def _on_regex_alarm(signum: int, frame: object) -> None:
    raise _RegexTimeoutError


def _regex_matches(pattern: str, value: str) -> bool:
    """Run `re.search(pattern, value)`, aborting (as "no match") past `_REGEX_TIMEOUT_SECONDS`."""
    previous_handler = signal.signal(signal.SIGALRM, _on_regex_alarm)
    signal.setitimer(signal.ITIMER_REAL, _REGEX_TIMEOUT_SECONDS)
    try:
        return re.search(pattern, value) is not None
    except _RegexTimeoutError:
        logger.warning("Regex filter exceeded %ss budget: %r", _REGEX_TIMEOUT_SECONDS, pattern)
        return False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _now() -> datetime:
    """Return the current time as naive UTC, matching how Postgres stores timestamps."""
    return datetime.now(UTC).replace(tzinfo=None)


def _with_scalar_defaults(model: type[Any], data: dict[str, Any]) -> dict[str, Any]:
    """Fill in a column's Python-side scalar `default=` for any field missing from `data`.

    SQLAlchemy only applies `mapped_column(default=...)` when a row is actually
    flushed to a real database -- this repository never flushes anywhere, so a mixin
    like Draftable/Lockable (see app.models.mixins) would otherwise leave its column
    unset (None) on a record created without that field, instead of the column's
    own declared default (e.g. `is_draft=True`).
    """
    defaults = {
        column.key: column.default.arg
        for column in sa_inspect(model).columns
        if column.key not in data and column.default is not None and column.default.is_scalar
    }
    return {**defaults, **data}


_PREDICATES: dict[FilterOp, Callable[[Any, Any], bool]] = {
    FilterOp.EQ: lambda value, target: bool(value == target),
    FilterOp.NE: lambda value, target: bool(value != target),
    FilterOp.LT: lambda value, target: bool(value < target),
    FilterOp.LTE: lambda value, target: bool(value <= target),
    FilterOp.GT: lambda value, target: bool(value > target),
    FilterOp.GTE: lambda value, target: bool(value >= target),
    FilterOp.IN: lambda value, target: value in target,
    FilterOp.CONTAINS: lambda value, target: str(target) in str(value),
    FilterOp.ICONTAINS: lambda value, target: str(target).casefold() in str(value).casefold(),
    FilterOp.REGEX: lambda value, target: _regex_matches(str(target), str(value)),
}


def _known_field(instance: object, field: str) -> Any:  # noqa: ANN401
    """Return `field` off `instance`, or raise if it isn't a mapped column of its model.

    Same defense-in-depth rationale as SQLAlchemyRepository._column: FilterClause.field/
    SortClause.field are only meant to reach here already validated against a
    resource's schema (app.controllers.crud_query.parse_filters/parse_sort) -- this
    check is what turns a caller that bypasses that validation into a clear error
    instead of either an AttributeError (an unrecognized name) or a silent read of an
    unintended attribute.
    """
    mapper = sa_inspect(type(instance))
    assert mapper is not None  # noqa: S101 -- `instance` is always a mapped IdentifiedBase
    if field not in mapper.columns.keys():  # noqa: SIM118 -- ColumnCollection, not a dict
        raise ValueError(f"{field!r} is not a filterable/sortable column of {type(instance)!r}")
    return getattr(instance, field)


def _matches(instance: object, clause: FilterClause) -> bool:
    value = _known_field(instance, clause.field)
    return _PREDICATES[clause.op](value, clause.value)


def _sort_key(instance: object, clause: SortClause) -> Any:  # noqa: ANN401
    return _known_field(instance, clause.field)


def _is_visible(instance: object, *, include_archived: bool, include_unpublished: bool) -> bool:
    """Whether `instance` passes the default Archivable/Schedulable exclusion rules."""
    if not include_archived and getattr(instance, "archived_at", None) is not None:
        return False
    if not include_unpublished:
        publish_at = getattr(instance, "publish_at", None)
        unpublish_at = getattr(instance, "unpublish_at", None)
        now = _now()
        if publish_at is not None and publish_at > now:
            return False
        if unpublish_at is not None and unpublish_at <= now:
            return False
    return True


def _raise_if_locked(instance: object, data: dict[str, Any] | None) -> None:
    """Raise RecordLockedError unless `instance` isn't locked or `data` unlocks-only.

    See app.models.mixins.Lockable's own docstring: the unlock escape hatch only
    applies when `data` is exactly `{"is_locked": False}`, not a PATCH that also
    changes other fields in the same request.
    """
    if not getattr(instance, "is_locked", False):
        return
    if data is not None and data == {"is_locked": False}:
        return
    raise RecordLockedError(f"record {getattr(instance, 'id', '?')!r} is locked")


class InMemoryRepository[ModelT: IdentifiedBase]:
    """Repository backed by a plain dict, keyed by an auto-incrementing id."""

    def __init__(self, model: type[ModelT]) -> None:
        """Bind this repository to the SQLAlchemy model class it stores instances of."""
        self._model = model
        self._records: dict[int, ModelT] = {}
        self._next_id = 1

    def _matching(self, filters: Sequence[FilterClause]) -> list[ModelT]:
        return [
            instance
            for instance in self._records.values()
            if all(_matches(instance, clause) for clause in filters)
        ]

    def _sorted(self, instances: list[ModelT], sort: Sequence[SortClause]) -> list[ModelT]:
        result = instances
        for clause in reversed(sort):
            result = sorted(
                result, key=lambda instance: _sort_key(instance, clause), reverse=clause.descending
            )
        return result

    async def get(
        self, record_id: int, *, include_archived: bool = False, include_unpublished: bool = False
    ) -> ModelT | None:
        """Return the record with the given id, or None if it doesn't exist."""
        instance = self._records.get(record_id)
        if instance is None:
            return None
        if not _is_visible(
            instance, include_archived=include_archived, include_unpublished=include_unpublished
        ):
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
        matching = [
            instance
            for instance in self._matching(filters)
            if _is_visible(
                instance, include_archived=include_archived, include_unpublished=include_unpublished
            )
        ]
        ordered = self._sorted(matching, sort) if sort else matching
        return ordered[skip : skip + limit]

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
        return len(
            [
                instance
                for instance in self._matching(filters)
                if _is_visible(
                    instance,
                    include_archived=include_archived,
                    include_unpublished=include_unpublished,
                )
            ]
        )

    async def create(self, data: dict[str, Any]) -> ModelT:
        """Create a new record from the given field values and return it."""
        now = _now()
        data = _with_scalar_defaults(self._model, data)
        instance = self._model(id=self._next_id, created_at=now, updated_at=now, **data)
        self._records[self._next_id] = instance
        self._next_id += 1
        return instance

    async def update(  # pragma: no cover -- see module docstring
        self, record_id: int, data: dict[str, Any]
    ) -> ModelT | None:
        """Apply the given field values to the record with the given id, if it exists."""
        instance = self._records.get(record_id)
        if instance is None or getattr(instance, "archived_at", None) is not None:
            return None
        _raise_if_locked(instance, data)
        for field, value in data.items():
            setattr(instance, field, value)
        instance.updated_at = _now()
        return instance

    async def delete(self, record_id: int) -> bool:  # pragma: no cover -- see module docstring
        """Delete the record with the given id; return whether it existed."""
        instance = self._records.get(record_id)
        if instance is None:
            return False
        if hasattr(instance, "archived_at"):
            if instance.archived_at is not None:
                return False
            _raise_if_locked(instance, None)
            instance.archived_at = _now()
            return True
        _raise_if_locked(instance, None)
        del self._records[record_id]
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
        instances = [
            instance
            for instance in self._matching(filters)
            if _is_visible(instance, include_archived=False, include_unpublished=True)
        ]
        for instance in instances:
            _raise_if_locked(instance, data)
        now = _now()
        for instance in instances:
            for field, value in data.items():
                setattr(instance, field, value)
            instance.updated_at = now
        return instances

    async def delete_many(self, *, filters: Sequence[FilterClause]) -> Sequence[ModelT]:
        """Delete every record matching the filters; return the records that were deleted.

        Excludes already-archived rows by default, same as update_many above -- a
        not-yet-or-no-longer-published row is still reachable (see update_many's
        own docstring for why).
        """
        instances = [
            instance
            for instance in self._matching(filters)
            if _is_visible(instance, include_archived=False, include_unpublished=True)
        ]
        for instance in instances:
            _raise_if_locked(instance, None)
        now = _now()
        for instance in instances:
            if hasattr(instance, "archived_at"):
                instance.archived_at = now
            else:
                del self._records[instance.id]  # pragma: no cover -- see module docstring
        return instances

    async def restore(  # pragma: no cover -- see module docstring
        self, record_id: int
    ) -> ModelT | None:
        """Clear `archived_at` on the record with the given id; return it, or None."""
        instance = self._records.get(record_id)
        if instance is None or not hasattr(instance, "archived_at"):
            return None
        instance.archived_at = None
        return instance

    async def restore_many(self, *, filters: Sequence[FilterClause]) -> Sequence[ModelT]:
        """Clear `archived_at` on every record matching the filters; return them."""
        instances = [
            instance for instance in self._matching(filters) if hasattr(instance, "archived_at")
        ]
        for instance in instances:
            instance.archived_at = None
        return instances
