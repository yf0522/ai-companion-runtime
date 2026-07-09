from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, time, timedelta
from typing import Optional

from app.tools.base import ToolBase, ToolResult

logger = logging.getLogger(__name__)

DAILY_KEYWORDS = ["吃药", "量血压", "测血糖", "吃饭", "喝水", "做操", "散步", "锻炼", "吃早饭", "吃午饭", "吃晚饭"]
ONCE_KEYWORDS = ["打电话", "买", "取", "寄", "明天", "后天", "下周"]

SNOOZE_PATTERNS = [
    r"晚点再吃",
    r"等会儿再吃",
    r"一会儿再吃",
    r"过一会儿再提醒",
    r"晚点再提醒",
    r"再提醒我",
    r"推迟.*提醒",
    r"半小时后再说",
    r"(\d+)\s*分钟后再",
    r"半小时后再提醒",
]


def detect_snooze(text: str) -> Optional[int]:
    """Return snooze minutes if text is a snooze request, else None."""
    if not text:
        return None
    if not any(re.search(p, text) for p in SNOOZE_PATTERNS):
        return None
    m = re.search(r"(\d+)\s*分钟", text)
    if m:
        return max(1, min(int(m.group(1)), 24 * 60))
    if "半小时" in text:
        return 30
    if "一小时" in text or "1小时" in text:
        return 60
    return 30


def detect_schedule_type(text: str) -> Optional[str]:
    for kw in DAILY_KEYWORDS:
        if kw in text:
            return "daily"
    for kw in ONCE_KEYWORDS:
        if kw in text:
            return "once"
    return None


def parse_time_from_text(text: str) -> Optional[time]:
    m = re.search(r"下午\s*(\d{1,2})\s*(?:点|:)\s*(\d{1,2})?", text)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if h < 12:
            h += 12
        return time(h, mi)

    m = re.search(r"上午\s*(\d{1,2})\s*(?:点|:)\s*(\d{1,2})?", text)
    if m:
        return time(int(m.group(1)), int(m.group(2)) if m.group(2) else 0)

    m = re.search(r"(\d{1,2})\s*(?:点|:)\s*(\d{1,2})?", text)
    if m:
        return time(int(m.group(1)), int(m.group(2)) if m.group(2) else 0)

    return None


def _normalize_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))


class ReminderTool(ToolBase):
    name = "reminder"
    description = "设置提醒"
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "提醒内容"},
            "time": {"type": "string", "description": "提醒时间"},
        },
    }

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "")
        snooze_minutes = detect_snooze(query)
        if snooze_minutes is not None:
            return await self._execute_snooze(params, snooze_minutes)

        content, remind_time = self._parse_reminder(query)

        if not content:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="无法理解提醒内容",
            )

        if remind_time is None:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="请告诉我具体时间，例如：每天晚上8点提醒我吃药",
                data={"reason": "missing_time"},
            )

        time_str = remind_time.strftime("%Y-%m-%d %H:%M")
        timer_data = self._build_timer_data(content, remind_time, query)
        schedule_type = "daily" if timer_data.get("repeat_mode") == "daily" else "once"

        reminder_id: str | None = None
        next_fire_at = remind_time
        user_id = params.get("user_id")
        if user_id:
            try:
                reminder_id, next_fire_at = await self._persist_reminder(
                    user_id=str(user_id),
                    title=content,
                    schedule_type=schedule_type,
                    remind_time=remind_time,
                    timer_data=timer_data,
                    trace_id=params.get("trace_id"),
                )
            except Exception as e:
                logger.error(f"Reminder persistence failed: {e}")
                return ToolResult(
                    tool_name=self.name,
                    status="failed",
                    display_text="提醒解析成功，但保存失败，请稍后重试",
                    data={"reason": "persist_failed", "error": str(e)},
                )

        payload = {
            "action": "reminder_create",
            "label": content,
            "display_time": time_str,
            "reminder_id": reminder_id,
            "next_fire_at": next_fire_at.isoformat() if next_fire_at else None,
            "schedule_type": schedule_type,
            **timer_data,
        }

        logger.info(
            "Reminder set: '%s' at %s (type=%s id=%s)",
            content,
            time_str,
            timer_data.get("timer_type"),
            reminder_id,
        )

        return ToolResult(
            tool_name=self.name,
            status="success",
            data=payload,
            display_text=f"已设置提醒：{content}（{time_str}）",
        )

    async def _execute_snooze(self, params: dict, snooze_minutes: int) -> ToolResult:
        user_id = params.get("user_id")
        if not user_id:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="无法推迟提醒：缺少用户信息",
                data={"reason": "missing_user", "action": "reminder_snooze"},
            )
        try:
            reminder_id, title, next_fire = await self._snooze_reminder(
                user_id=str(user_id),
                snooze_minutes=snooze_minutes,
            )
        except LookupError:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="还没有可推迟的提醒，请先设置吃药或复诊提醒",
                data={"reason": "no_reminder", "action": "reminder_snooze"},
            )
        except Exception as e:
            logger.error(f"Reminder snooze failed: {e}")
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="推迟提醒失败，请稍后重试",
                data={"reason": "snooze_failed", "error": str(e), "action": "reminder_snooze"},
            )

        label = title or "提醒"
        display = f"好的，我{snooze_minutes}分钟后再提醒您{label}"
        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=display,
            data={
                "action": "reminder_snooze",
                "reminder_id": reminder_id,
                "label": label,
                "snooze_minutes": snooze_minutes,
                "next_fire_at": next_fire.isoformat() if next_fire else None,
            },
        )

    async def _snooze_reminder(
        self,
        user_id: str,
        snooze_minutes: int,
    ) -> tuple[str, str, datetime]:
        from sqlalchemy import or_, select

        from app.db.session import async_session
        from app.db.models import Reminder

        db_user_id = _normalize_user_id(user_id)
        next_fire = datetime.utcnow() + timedelta(minutes=snooze_minutes)

        async with async_session() as db:
            med = await db.execute(
                select(Reminder)
                .where(
                    Reminder.user_id == db_user_id,
                    Reminder.is_active.is_(True),
                    or_(Reminder.title.contains("药"), Reminder.title.contains("吃药")),
                )
                .order_by(Reminder.created_at.desc())
                .limit(1)
            )
            row = med.scalar_one_or_none()
            if not row:
                any_r = await db.execute(
                    select(Reminder)
                    .where(Reminder.user_id == db_user_id, Reminder.is_active.is_(True))
                    .order_by(Reminder.created_at.desc())
                    .limit(1)
                )
                row = any_r.scalar_one_or_none()
            if not row:
                raise LookupError("no active reminder")

            row.next_fire_at = next_fire
            row.is_active = True
            await db.commit()
            await db.refresh(row)
            return str(row.id), row.title, next_fire

    async def _persist_reminder(
        self,
        user_id: str,
        title: str,
        schedule_type: str,
        remind_time: datetime,
        timer_data: dict,
        trace_id: str | None,
    ) -> tuple[str, datetime]:
        from app.db.session import async_session
        from app.db.models import Reminder

        db_user_id = _normalize_user_id(user_id)
        now = datetime.utcnow()
        next_fire = remind_time
        if timer_data.get("timer_type") == "countdown":
            next_fire = now + timedelta(seconds=int(timer_data.get("duration_sec") or 0))
        elif next_fire.replace(tzinfo=None) < now:
            if schedule_type == "daily":
                next_fire = next_fire + timedelta(days=1)
            else:
                next_fire = next_fire + timedelta(days=1)

        async with async_session() as db:
            row = Reminder(
                user_id=db_user_id,
                title=title,
                description=f"trace_id={trace_id}" if trace_id else None,
                schedule_type=schedule_type,
                time_of_day=remind_time,
                next_fire_at=next_fire,
                is_active=True,
                created_by="chat",
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return str(row.id), next_fire

    def _parse_reminder(self, query: str) -> tuple[str, datetime | None]:
        """Extract reminder content and time from query."""
        now = datetime.now()
        remind_time = None

        time_patterns: list[tuple[str, str, str, callable | None]] = [
            (r"(\d+)\s*分钟后", "countdown", "once",
             lambda m: now + timedelta(minutes=int(m.group(1)))),
            (r"(\d+)\s*小时后", "countdown", "once",
             lambda m: now + timedelta(hours=int(m.group(1)))),
            (r"(\d+)\s*秒后", "countdown", "once",
             lambda m: now + timedelta(seconds=int(m.group(1)))),
            (r"每天[早上早晨]+(\d{1,2})点", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0)),
            (r"每天[下午晚上]+(\d{1,2})点", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)) + 12, minute=0, second=0, microsecond=0)),
            (r"每天(\d{1,2})点(\d{2})分", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)),
            (r"每天(\d{1,2})点", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0)),
            (r"明天[早上早晨]*(\d{1,2})点", "alarm", "once",
             lambda m: (now + timedelta(days=1)).replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0)),
            (r"今天[早上早晨]*(\d{1,2})点", "alarm", "once",
             lambda m: now.replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0)),
            (r"[下午晚上]+(\d{1,2})点", "alarm", "once",
             lambda m: now.replace(hour=int(m.group(1)) + 12, minute=0, second=0, microsecond=0)),
            (r"(\d{1,2})点(\d{2})分", "alarm", "once",
             lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)),
            (r"(\d{1,2})点", "alarm", "once",
             lambda m: now.replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0)),
        ]

        matched_pattern = None
        for pattern, timer_type, repeat_mode, time_fn in time_patterns:
            match = re.search(pattern, query)
            if match:
                try:
                    remind_time = time_fn(match)
                    matched_pattern = (timer_type, repeat_mode, pattern)
                except (ValueError, OverflowError):
                    pass
                break

        content = query
        for prefix in ["提醒我", "别忘了", "记得", "帮我记住"]:
            content = content.replace(prefix, "")
        if matched_pattern:
            content = re.sub(matched_pattern[2], "", content)
        content = content.strip("，。, ")
        for word in ["设置", "定一个", "一个"]:
            if content.startswith(word):
                content = content[len(word):]
        content = content.strip("，。, ")

        return content or query, remind_time

    def _build_timer_data(self, content: str, remind_time: datetime | None, query: str) -> dict:
        """Build structured timer data for the ESP32 device."""
        if not remind_time:
            return {"timer_type": "reminder", "repeat_mode": "once", "duration_sec": 0}

        now = datetime.now()
        diff_seconds = int((remind_time - now).total_seconds())
        if diff_seconds < 0:
            diff_seconds += 86400

        if "每天" in query:
            return {
                "timer_type": "alarm",
                "repeat_mode": "daily",
                "hour": remind_time.hour,
                "minute": remind_time.minute,
            }

        if re.search(r"\d+\s*(分钟|小时|秒)后", query):
            return {
                "timer_type": "countdown",
                "repeat_mode": "once",
                "duration_sec": diff_seconds,
            }

        return {
            "timer_type": "alarm",
            "repeat_mode": "once",
            "hour": remind_time.hour,
            "minute": remind_time.minute,
        }
