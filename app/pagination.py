"""Pagination bounds shared by event and participant queries."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageBounds:
    page: int
    pages: int
    size: int

    @property
    def offset(self) -> int:
        return self.page * self.size


def page_bounds(total: int, page: int, size: int) -> PageBounds:
    pages = max(1, (total + size - 1) // size)
    return PageBounds(min(max(0, page), pages - 1), pages, size)
