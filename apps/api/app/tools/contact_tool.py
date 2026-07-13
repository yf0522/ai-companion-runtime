from __future__ import annotations

import logging
import re

from app.config.settings import settings
from app.tools.base import ToolBase, ToolResult
from app.workers.notification_outbox_worker import (
    create_family_contact_request_pipeline,
    deliver_notification_outbox,
)

logger = logging.getLogger(__name__)

_FAMILY = r"(?:家人|家属|孩子|女儿|儿子)"
_CONTACT_NEGATIVE = re.compile(
    rf"(?:不用|不要|不需要|不想|不打算|不会).{{0,12}}"
    rf"(?:联系|通知|告诉|让).{{0,8}}{_FAMILY}|"
    rf"(?:联系|通知|告诉).{{0,6}}{_FAMILY}.{{0,4}}(?:了吗|了没|过吗|没有)$"
)
_CONTACT_POSITIVE = (
    re.compile(rf"^(?:请|麻烦|帮我|能不能|可以)?(?:联系|通知|告诉).{{0,4}}{_FAMILY}"),
    re.compile(
        rf"^(?:请|麻烦|帮我|让|我想让|想让|希望|我希望|需要|我需要|能不能让|可以让)"
        rf".{{0,6}}{_FAMILY}.{{0,12}}"
        r"(?:联系我|给我打电话|知道我需要帮助|来帮我|帮帮我|来看看我)"
    ),
    re.compile(
        rf"^(?:(?:我希望|我想).{{0,4}}你|(?:请|麻烦).{{0,4}}(?:你)?)"
        rf"(?:联系|通知|告诉).{{0,4}}{_FAMILY}"
    ),
)


def is_explicit_family_contact_request(query: str | None) -> bool:
    text = str(query or "").strip()
    if not text or _CONTACT_NEGATIVE.search(text):
        return False
    return any(pattern.search(text) for pattern in _CONTACT_POSITIVE)


class ContactFamilyTool(ToolBase):
    name = "contact"
    description = (
        "Record an explicit elder request for family contact. The result reports "
        "persistence and queue state only; it never claims delivery without a receipt."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["request_contact"],
                "description": "Request that verified family contacts reach the elder",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    async def execute(self, params: dict) -> ToolResult:
        action = str(params.get("action") or "request_contact").strip().lower()
        if action != "request_contact":
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="当前只支持请求家人联系。",
                data={"reason": "unsupported_action", "action": action},
            )

        user_id = str(params.get("user_id") or "").strip()
        trace_id = str(params.get("trace_id") or "").strip()
        if not user_id or not trace_id:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="这次没有成功发出联系请求，请直接联系身边可信任的人。",
                data={"reason": "missing_trusted_context", "action": "contact_help_request"},
            )

        query = re.sub(r"\s+", " ", str(params.get("query") or "需要帮助")).strip()[:240]
        summary = f"长者主动请求家人联系：{query or '需要帮助'}"
        try:
            result = await create_family_contact_request_pipeline(
                user_id=user_id,
                summary=summary,
                trace_id=trace_id,
            )
        except Exception:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="这次没有成功发出联系请求，请直接联系身边可信任的人。",
                data={"reason": "persistence_failed", "action": "contact_help_request"},
            )

        delivery_status = str(result.get("delivery_status") or "unknown")
        if result.get("status") == "failed":
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="这次没有成功发出联系请求，请直接联系身边可信任的人。",
                data={**result, "action": "contact_help_request"},
            )

        outbox_ids = list(result.get("outbox_ids") or [])
        if outbox_ids and settings.enable_celery_tasks:
            try:
                deliver_notification_outbox.delay()
                result["delivery_task_queued"] = True
            except Exception as exc:
                # Persistence is the source of truth. A broker outage must not
                # turn a committed outbox row into a false-negative response;
                # beat/retry workers can still deliver it later.
                logger.warning(
                    "Contact outbox scheduling failed error_class=%s code=contact_schedule_failed",
                    type(exc).__name__,
                )
                result["delivery_task_queued"] = False
                result["delivery_schedule_error"] = "broker_unavailable"

        if delivery_status == "no_verified_contact":
            display_text = (
                "求助请求已记录，但目前没有可用的已验证联系人；"
                "请打开帮助页直接联系可信任的人，或请家属补充联系方式。"
            )
        elif delivery_status == "queued":
            display_text = "求助请求已记录并进入联系队列，送达状态还在确认。"
        elif delivery_status == "pending":
            display_text = "求助请求正在处理中，请不要重复发送；送达状态还在确认。"
        else:
            display_text = "求助请求已记录，是否送达请以家属端状态为准。"

        return ToolResult(
            tool_name=self.name,
            status="success",
            display_text=display_text,
            data={**result, "action": "contact_help_request"},
        )
