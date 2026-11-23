"""The limits of one run: a cap on the items it starts, one at a time."""

import threading
from collections.abc import Iterable


class Run:
    """Which items a run has started, its cap, and the lock that keeps work to one."""

    def __init__(self, limit: int, started: Iterable[str] = ()):
        self.limit = limit
        self.started: set[str] = set(started)
        self.summary: str | None = None
        self.lock = threading.Lock()

    def admit(self, item: str) -> bool:
        """Count the item as started, unless the cap is used up on other items."""
        if item not in self.started and len(self.started) >= self.limit:
            return False
        self.started.add(item)
        return True

    def unfinished(self, waiting: Iterable[str]) -> list[str]:
        """The waiting items the run must still work: retries, and new ones in cap."""
        return [
            item
            for item in waiting
            if item in self.started or len(self.started) < self.limit
        ]
