"""Pagination, filtering, and batch operation utilities."""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel, Field


T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


@dataclass
class PaginatedResponse(Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def create(cls, items: list[T], total: int, page: int, page_size: int) -> "PaginatedResponse[T]":
        total_pages = (total + page_size - 1) // page_size
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


class FilterParams(BaseModel):
    search: str | None = Field(default=None, description="Search across text fields")
    sort_by: str | None = Field(default=None, description="Field to sort by")
    sort_order: str = Field(default="asc", description="Sort direction: asc or desc")
    created_after: str | None = Field(default=None, description="ISO datetime filter")
    created_before: str | None = Field(default=None, description="ISO datetime filter")


class BatchOperationRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=50, description="Entity IDs to operate on")
    action: str = Field(..., description="Action: delete, archive, restore, update")


class BatchOperationResponse(BaseModel):
    succeeded: list[str]
    failed: dict[str, str]
    total: int


def paginate(items: list[Any], page: int = 1, page_size: int = 20) -> tuple[list[Any], int]:
    """Paginate a list of items. Returns (page_items, total_count)."""
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], total


def apply_filters(
    items: list[dict[str, Any]],
    search: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "asc",
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply search, sort, and custom filters to a list of items."""
    result = list(items)

    if search:
        search_lower = search.lower()
        result = [
            item for item in result
            if any(
                search_lower in str(v).lower()
                for v in item.values()
                if isinstance(v, (str, int, float))
            )
        ]

    if filters:
        for field, value in filters.items():
            if value is not None:
                result = [item for item in result if item.get(field) == value]

    if sort_by:
        reverse = sort_order.lower() == "desc"
        result = sorted(result, key=lambda x: x.get(sort_by, ""), reverse=reverse)

    return result


class EventEmitter:
    """Simple in-memory event emitter for SSE."""

    def __init__(self):
        self._subscribers: dict[str, list[callable]] = {}

    def subscribe(self, event_type: str, callback: callable) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(data)
                except Exception:
                    pass


_global_emitter = EventEmitter()


def get_event_emitter() -> EventEmitter:
    return _global_emitter


def format_sse(data: dict[str, Any], event: str | None = None) -> str:
    msg = f"data: {data!s}\n"
    if event:
        msg = f"event: {event}\n{msg}"
    return msg + "\n"