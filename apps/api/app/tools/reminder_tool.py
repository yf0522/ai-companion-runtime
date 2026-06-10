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

        # For V1, just acknowledge the reminder
        # Full Celery-based scheduling in Phase 4
        time_str = remind_time.strftime("%Y-%m-%d %H:%M") if remind_time else "稍后"

        logger.info(f"Reminder set: '{content}' at {time_str}")

        return ToolResult(
            tool_name=self.name,
            status="success",
            data={"content": content, "time": time_str},
            display_text=f"已设置提醒：{content}（{time_str}）",
        )

    def _parse_reminder(self, query: str) -> tuple[str, datetime | None]:
        """Extract reminder content and time from query."""
        now = datetime.now()
        remind_time = None

        # Time patterns
        time_patterns = {
            r"(\d+)\s*分钟后": lambda m: now + timedelta(minutes=int(m.group(1))),
            r"(\d+)\s*小时后": lambda m: now + timedelta(hours=int(m.group(1))),
            r"明天(\d{1,2})点": lambda m: now.replace(day=now.day + 1, hour=int(m.group(1)), minute=0, second=0),
            r"今天(\d{1,2})点": lambda m: now.replace(hour=int(m.group(1)), minute=0, second=0),
            r"下午(\d{1,2})点": lambda m: now.replace(hour=int(m.group(1)) + 12, minute=0, second=0),
            r"(\d{1,2})点(\d{2})": lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0),
        }

        for pattern, time_fn in time_patterns.items():
            match = re.search(pattern, query)
            if match:
                try:
                    remind_time = time_fn(match)
                except (ValueError, OverflowError):
                    pass
                break

        # Extract content: remove time parts and common prefixes
        content = query
        for prefix in ["提醒我", "别忘了", "记得", "帮我记住"]:
            content = content.replace(prefix, "")
        for pattern in time_patterns:
            content = re.sub(pattern, "", content)
        content = content.strip("，。, ")

        return content or query, remind_time
