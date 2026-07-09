from celery import Celery
from celery.schedules import crontab

from urllib.parse import quote, urlparse, urlunparse

from app.config.settings import settings


def _inject_redis_password(url: str, password: str) -> str:
    """Inject password into a Redis URL only if it doesn't already have credentials.

    The password is URL-encoded so special chars (@, /, :, #, %) don't break the URL.
    """
    parsed = urlparse(url)
    if parsed.password or parsed.username:
        # URL already has credentials — don't overwrite
        return url
    encoded_pw = quote(password, safe="")
    new_netloc = f":{encoded_pw}@{parsed.hostname}"
    if parsed.port:
        new_netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=new_netloc))


_broker_url = settings.celery_broker_url
if settings.redis_password:
    _broker_url = _inject_redis_password(_broker_url, settings.redis_password)

_result_backend = _broker_url

app = Celery("companion")
app.config_from_object({
    "broker_url": _broker_url,
    "result_backend": _result_backend,
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
    "check-due-reminders": {
        "task": "app.workers.reminder_scheduler.check_due_reminders",
        "schedule": 60.0,
    },
}

app.autodiscover_tasks([
    "app.workers.memory_worker",
    "app.workers.embedding_worker",
    "app.workers.reflection_worker",
    "app.workers.reminder_scheduler",
    "app.workers.notification_worker",
])
