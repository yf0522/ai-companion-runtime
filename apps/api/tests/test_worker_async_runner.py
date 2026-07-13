from __future__ import annotations

import asyncio
from pathlib import Path

from app.workers.async_runner import run_async_task


def test_run_async_task_reuses_one_process_local_event_loop():
    async def loop_identity() -> int:
        return id(asyncio.get_running_loop())

    first_loop = run_async_task(loop_identity)
    second_loop = run_async_task(loop_identity)

    assert second_loop == first_loop


def test_celery_async_entrypoints_do_not_create_per_task_event_loops():
    workers = Path(__file__).parents[1] / "app" / "workers"
    task_modules = (
        "embedding_worker.py",
        "memory_worker.py",
        "notification_outbox_worker.py",
        "reflection_worker.py",
        "reminder_scheduler.py",
    )

    for module_name in task_modules:
        source = (workers / module_name).read_text(encoding="utf-8")
        assert "asyncio.run(" not in source
