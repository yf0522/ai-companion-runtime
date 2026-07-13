"""Process-local event-loop bridge for synchronous Celery task entrypoints."""
from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

_runner: asyncio.Runner | None = None
_runner_pid: int | None = None
_runner_lock = threading.Lock()


def run_async_task(factory: Callable[[], Awaitable[T]]) -> T:
    """Run one async task on the event loop owned by this Celery child process.

    SQLAlchemy's async engine pools asyncpg connections that are bound to the
    event loop which created them. A fresh ``asyncio.run`` loop per Celery task
    can therefore reuse a pooled connection from a closed loop. Keeping one
    lazy runner per process preserves the connection/loop ownership contract.
    """
    global _runner, _runner_pid

    with _runner_lock:
        process_id = os.getpid()
        if _runner is None or _runner_pid != process_id:
            _runner = asyncio.Runner()
            _runner_pid = process_id
        return _runner.run(factory())
