"""
Read-only handlers. No state mutation. No domain aggregates loaded -
queries work with whatever the repo returns (can be DTOs or ORM models
mapped to response dataclasses).

Because queries are read-only they can bypass the domain layer entirely
and talk to read-optimised repo methods or even raw SQL projections.
"""

from __future__ import annotations
from dataclasses import dataclass

# Shared pagination input


@dataclass(frozen=True)
class PaginationParams:
    limit: int = 20
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if self.offset < 0:
            raise ValueError("offset cannot be negative")
