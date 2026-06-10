from celery import Celery
from celery.schedules import crontab

app = Celery("companion")
app.config_from_object({
    "broker_url": "redis://redis:6379/1",
    "result_backend": "redis://redis:6379/1",
    "task_serializer": "json",
    "result_serializer": "json",
    "accept_content": ["json"],
    "timezone": "Asia/Shanghai",
    "enable_utc": True,
    "task_routes": {
        "app.workers.memory_worker.*": {"queue": "memory"},
        "app.workers.embedding_worker.*": {"queue": "embedding"},
        "app.workers.reflection_worker.*": {"queue": "reflection"},
    },
})

app.conf.beat_schedule = {
    "daily-archive": {
        "task": "app.workers.memory_worker.daily_archive",
        "schedule": crontab(hour=3, minute=0),
    },
    "weekly-vector-cleanup": {
        "task": "app.workers.memory_worker.vector_cleanup",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),
    },
    "monthly-trace-archive": {
        "task": "app.workers.memory_worker.trace_cold_archive",
        "schedule": crontab(hour=2, minute=0, day_of_month=1),
    },
}

app.autodiscover_tasks([
    "app.workers.memory_worker",
    "app.workers.embedding_worker",
    "app.workers.reflection_worker",
])
