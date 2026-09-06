"""Generic repository protocol: the storage-agnostic contract app.interfaces talks to."""

from collections.abc import Sequence
from typing import Any, Protocol

from app.repositories.filtering import FilterClause, SortClause


class RecordLockedError(Exception):
    """Raised by update/update_many/delete/delete_many against a Lockable record.

    Raised when the existing row's `is_locked` is True and the mutation isn't the
    one explicit escape hatch: an `update`/`update_many` call whose own `data` sets
    `is_locked=False`. app.controllers.crud_actions catches this and raises
    HTTPException(423) -- see app.models.mixins.Lockable.
    """


class Repository[ModelT](Protocol):
    """Storage-agnostic CRUD contract for a single kind of persisted record."""

    async def get(
        self, record_id: int, *, include_archived: bool = False, include_unpublished: bool = False
    ) -> ModelT | None:
        """Return the record with the given id, or None if it doesn't exist.

        For a model carrying app.models.mixins.Archivable/Schedulable, an archived
        or not-yet-/no-longer-published record is treated as not found unless the
        matching `include_*` flag is set.
        """
        ...

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
        """Return up to `limit` matching records, skipping the first `skip`.

        See `get`'s docstring for `include_archived`/`include_unpublished`.
        """
        ...

    async def count(
        self,
        *,
        filters: Sequence[FilterClause] = (),
        include_archived: bool = False,
        include_unpublished: bool = False,
    ) -> int:
        """Return how many records match the given filters.

        See `get`'s docstring for `include_archived`/`include_unpublished`.
        """
        ...

    async def create(self, data: dict[str, Any]) -> ModelT:
        """Create and return a new record from the given field values."""
        ...

    async def update(self, record_id: int, data: dict[str, Any]) -> ModelT | None:
        """Update the record with the given id and return it, or None if it doesn't exist.

        Raises RecordLockedError for a Lockable record whose `is_locked` is True,
        unless `data` itself sets `is_locked=False` -- see RecordLockedError.
        """
        ...

    async def delete(self, record_id: int) -> bool:
        """Delete the record with the given id; return whether it existed.

        For a model carrying app.models.mixins.Archivable, this sets `archived_at`
        instead of issuing a real delete. Raises RecordLockedError for a Lockable
        record whose `is_locked` is True.
        """
        ...

    async def update_many(
        self, *, filters: Sequence[FilterClause], data: dict[str, Any]
    ) -> Sequence[ModelT]:
        """Apply the given field values to every record matching the filters; return them.

        Raises RecordLockedError (see `delete`'s docstring) for any matched record
        that's locked, unless `data` itself sets `is_locked=False`.
        """
        ...

    async def delete_many(self, *, filters: Sequence[FilterClause]) -> Sequence[ModelT]:
        """Delete every record matching the filters; return the records that were deleted.

        See `delete`'s docstring for the Archivable/Lockable behavior.
        """
        ...

    async def restore(self, record_id: int) -> ModelT | None:
        """Clear `archived_at` on the record with the given id; return it, or None.

        None both when the record doesn't exist and when the model isn't
        Archivable at all -- there's nothing to restore either way.
        """
        ...

    async def restore_many(self, *, filters: Sequence[FilterClause]) -> Sequence[ModelT]:
        """Clear `archived_at` on every record matching the filters; return them."""
        ...
