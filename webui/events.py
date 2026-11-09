"""What a run tells the screen, and the one run the app may have going.

A run (live or demo) emits ``RunEvent``s from a background thread into its
``RunHandle``; the page reads them by index each refresh. The active handle
lives at module level, which Streamlit shares across every session in the
process, so a browser refresh or a second tab finds the same run.
"""

import threading
import time
from dataclasses import dataclass
from typing import Literal


@dataclass
class RunEvent:
    kind: Literal["stage", "report", "done", "error"]
    stage: str | None = None
    status: str | None = None
    title: str | None = None
    content: str | None = None
    report_dir: str | None = None
    rating: str | None = None
    detail: str | None = None   # an error's traceback


class RunHandle:
    def __init__(self, label: str):
        self.label = label
        self.started_at = time.monotonic()
        self._events: list[RunEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: RunEvent) -> None:
        with self._lock:
            self._events.append(event)

    def events_since(self, index: int) -> list[RunEvent]:
        with self._lock:
            return list(self._events[index:])

    @property
    def finished(self) -> bool:
        with self._lock:
            return any(e.kind in ("done", "error") for e in self._events)


_active: RunHandle | None = None
_active_lock = threading.Lock()


def active_run() -> RunHandle | None:
    with _active_lock:
        return _active


def set_active_run(handle: RunHandle | None) -> None:
    global _active
    with _active_lock:
        _active = handle
