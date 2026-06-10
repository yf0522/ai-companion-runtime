from __future__ import annotations

import ast
import logging
import operator
import re

from app.tools.base import ToolBase, ToolResult

logger = logging.getLogger(__name__)

# Safe operators
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
}


def _safe_eval(node):
    """Safely evaluate a math expression AST node."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value}")
    elif isinstance(node, ast.BinOp):
        op_func = _OPERATORS.get(type(node.op))
        if not op_func:
            raise ValueError(f"Unsupported operator: {type(node.op)}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return op_func(left, right)
    elif isinstance(node, ast.UnaryOp):
        op_func = _OPERATORS.get(type(node.op))
        if not op_func:
            raise ValueError(f"Unsupported unary operator: {type(node.op)}")
        return op_func(_safe_eval(node.operand))
    else:
        raise ValueError(f"Unsupported node: {type(node)}")


class CalculatorTool(ToolBase):
    name = "calculator"
    description = "计算数学表达式"
    parameters_schema = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式"},
        },
    }

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "")
        expr = self._extract_expression(query)

        if not expr:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="无法识别数学表达式",
            )

        try:
            tree = ast.parse(expr, mode="eval")
            result = _safe_eval(tree)
            # Format nicely
            if isinstance(result, float) and result == int(result):
                result = int(result)
            display = f"{expr} = {result}"
            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"expression": expr, "result": result},
                display_text=display,
            )
        except Exception as e:
            logger.warning(f"Calculator error: {e}")
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text=f"计算失败: {expr}",
            )

    def _extract_expression(self, query: str) -> str:
        """Extract math expression from natural language."""
        # Try to find math-like patterns
        # Replace Chinese math operators
        q = query.replace("×", "*").replace("÷", "/").replace("加", "+").replace("减", "-")
        q = q.replace("乘", "*").replace("除以", "/")

        # Find expression-like substring
        match = re.search(r"[\d\.\s\+\-\*/%\(\)]+", q)
        if match:
            expr = match.group(0).strip()
            if any(c.isdigit() for c in expr):
                return expr
        return ""
