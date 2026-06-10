from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from typing import Optional

from minio import Minio

from app.config.settings import settings

logger = logging.getLogger(__name__)

_client: Optional[Minio] = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        logger.info(f"MinIO connected: {settings.minio_endpoint}")
    return _client


def ensure_buckets():
    """Ensure all required buckets exist."""
    client = get_minio()
    for bucket in ["archive", "attachments", "traces"]:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info(f"Created bucket: {bucket}")


# ==================== Archive Operations ====================

def archive_messages(user_id: str, date: str, messages: list[dict]):
    """Archive messages as JSONL to MinIO.
    Path: archive/{user_id}/{yyyy}/{mm}/{dd}.jsonl
    """
    client = get_minio()
    dt = datetime.strptime(date, "%Y-%m-%d")
    path = f"{user_id}/{dt.strftime('%Y/%m')}/{dt.strftime('%d')}.jsonl"

    lines = [json.dumps(msg, ensure_ascii=False) for msg in messages]
    content = "\n".join(lines)
    data = content.encode("utf-8")

    client.put_object(
        bucket_name="archive",
        object_name=path,
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/jsonl",
    )
    logger.info(f"Archived {len(messages)} messages to archive/{path}")


def get_archived_messages(user_id: str, date: str) -> list[dict]:
    """Retrieve archived messages for a date."""
    client = get_minio()
    dt = datetime.strptime(date, "%Y-%m-%d")
    path = f"{user_id}/{dt.strftime('%Y/%m')}/{dt.strftime('%d')}.jsonl"

    try:
        response = client.get_object("archive", path)
        content = response.read().decode("utf-8")
        response.close()
        response.release_conn()

        messages = []
        for line in content.strip().split("\n"):
            if line:
                messages.append(json.loads(line))
        return messages
    except Exception as e:
        logger.warning(f"Failed to read archive/{path}: {e}")
        return []


# ==================== Attachment Operations ====================

def upload_attachment(
    user_id: str,
    message_id: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload user attachment. Returns the object path."""
    client = get_minio()
    path = f"{user_id}/{message_id}/{filename}"

    client.put_object(
        bucket_name="attachments",
        object_name=path,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    logger.info(f"Uploaded attachment: attachments/{path}")
    return path


def get_attachment_url(user_id: str, message_id: str, filename: str) -> str:
    """Get presigned URL for attachment download."""
    client = get_minio()
    path = f"{user_id}/{message_id}/{filename}"
    from datetime import timedelta
    url = client.presigned_get_object("attachments", path, expires=timedelta(hours=1))
    return url


# ==================== Trace Archive Operations ====================

def archive_trace(trace_id: str, trace_data: dict):
    """Archive a trace to MinIO cold storage.
    Path: traces/{yyyy}/{mm}/{trace_id}.json
    """
    client = get_minio()
    now = datetime.now()
    path = f"{now.strftime('%Y/%m')}/{trace_id}.json"

    content = json.dumps(trace_data, ensure_ascii=False, indent=2)
    data = content.encode("utf-8")

    client.put_object(
        bucket_name="traces",
        object_name=path,
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/json",
    )
    logger.info(f"Archived trace: traces/{path}")


def get_archived_trace(trace_id: str, year: int, month: int) -> Optional[dict]:
    """Retrieve an archived trace."""
    client = get_minio()
    path = f"{year:04d}/{month:02d}/{trace_id}.json"

    try:
        response = client.get_object("traces", path)
        content = response.read().decode("utf-8")
        response.close()
        response.release_conn()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Failed to read trace archive: {e}")
        return None


# ==================== Utility ====================

def list_archive_dates(user_id: str) -> list[str]:
    """List available archive dates for a user."""
    client = get_minio()
    prefix = f"{user_id}/"
    dates = set()
    try:
        objects = client.list_objects("archive", prefix=prefix, recursive=True)
        for obj in objects:
            # Parse date from path: user_id/yyyy/mm/dd.jsonl
            parts = obj.object_name.split("/")
            if len(parts) >= 4:
                year, month = parts[1], parts[2]
                day = parts[3].replace(".jsonl", "")
                dates.add(f"{year}-{month}-{day}")
    except Exception as e:
        logger.warning(f"Failed to list archive dates: {e}")
    return sorted(dates)
