"""Tool honesty: failed tools must not be verbally promised as success."""
from __future__ import annotations

from app.tools.base import ToolResult
from app.tools.honesty import enforce_no_verbal_promise


def test_honesty_helper_blocks_false_success():
    results = [
        ToolResult(
            tool_name="caretask",
            status="failed",
            display_text="提醒解析成功，但保存失败，请稍后重试",
        )
    ]
    claimed = "好的，已帮你设置吃药提醒了，到时候我会叫你。"
    fixed = enforce_no_verbal_promise(claimed, results)
    assert "已帮你设置" not in fixed
    assert "没有成功" in fixed or "失败" in fixed


def test_success_tools_leave_response_alone():
    results = [
        ToolResult(
            tool_name="caretask",
            status="success",
            display_text="已创建照护任务：吃药",
        )
    ]
    text = "已创建照护任务：吃药"
    assert enforce_no_verbal_promise(text, results) == text
