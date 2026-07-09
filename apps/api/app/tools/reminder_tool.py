from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from app.tools.base import ToolBase, ToolResult

logger = logging.getLogger(__name__)


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
        content, remind_time = self._parse_reminder(query)

        if not content:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="无法理解提醒内容",
            )

        time_str = remind_time.strftime("%Y-%m-%d %H:%M") if remind_time else "稍后"
        timer_data = self._build_timer_data(content, remind_time, query)

        logger.info(f"Reminder set: '{content}' at {time_str} (type={timer_data.get('timer_type')})")

        return ToolResult(
            tool_name=self.name,
            status="success",
            data={
                "action": "reminder_create",
                "label": content,
                "display_time": time_str,
                **timer_data,
            },
            display_text=f"已设置提醒：{content}（{time_str}）",
        )

    def _parse_reminder(self, query: str) -> tuple[str, datetime | None]:
        """Extract reminder content and time from query."""
        now = datetime.now()
        remind_time = None

        # Time patterns: (pattern, timer_type, repeat_mode, hour_fn_or_none)
        # For countdown patterns: hour_fn returns (now + delta)
        # For daily alarm patterns: hour_fn returns (hour, minute)
        time_patterns: list[tuple[str, str, str, callable | None]] = [
            # Countdown patterns → TIMER_COUNTDOWN, once
            (r"(\d+)\s*分钟后", "countdown", "once",
             lambda m: now + timedelta(minutes=int(m.group(1)))),
            (r"(\d+)\s*小时后", "countdown", "once",
             lambda m: now + timedelta(hours=int(m.group(1)))),
            (r"(\d+)\s*秒后", "countdown", "once",
             lambda m: now + timedelta(seconds=int(m.group(1)))),
            # Daily alarm patterns → TIMER_ALARM, daily
            (r"每天[早上早晨]+(\d{1,2})点", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0)),
            (r"每天[下午晚上]+(\d{1,2})点", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)) + 12, minute=0, second=0, microsecond=0)),
            (r"每天(\d{1,2})点(\d{2})分", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)),
            (r"每天(\d{1,2})点", "alarm", "daily",
             lambda m: now.replace(hour=int(m.group(1)), minute=0, second=0, microsecond=0)),
            # One-shot alarm patterns → TIMER_ALARM, once
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

        # Extract content: remove time parts and common prefixes
        content = query
        for prefix in ["提醒我", "别忘了", "记得", "帮我记住"]:
            content = content.replace(prefix, "")
        if matched_pattern:
            content = re.sub(matched_pattern[2], "", content)
        content = content.strip("，。, ")
        # Also strip common surrounding words
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
            diff_seconds += 86400  # next day if time already passed today

        # Check if this is a daily alarm (contains "每天")
        if "每天" in query:
            return {
                "timer_type": "alarm",
                "repeat_mode": "daily",
                "hour": remind_time.hour,
                "minute": remind_time.minute,
            }

        # Countdown if it's a relative time ("X分钟后", "X小时后", "X秒后")
        if re.search(r"\d+\s*(分钟|小时|秒)后", query):
            return {
                "timer_type": "countdown",
                "repeat_mode": "once",
                "duration_sec": diff_seconds,
            }

        # Default: one-shot alarm at specific clock time
        return {
            "timer_type": "alarm",
            "repeat_mode": "once",
            "hour": remind_time.hour,
            "minute": remind_time.minute,
        }
