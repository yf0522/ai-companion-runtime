from __future__ import annotations

import logging

import httpx

from app.tools.base import ToolBase, ToolResult

logger = logging.getLogger(__name__)


class WeatherTool(ToolBase):
    name = "weather"
    description = "查询指定城市的天气信息"
    parameters_schema = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名称"},
        },
    }

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "")
        city = self._extract_city(query)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://wttr.in/{city}",
                    params={"format": "j1"},
                    headers={"Accept-Language": "zh-CN"},
                )
                resp.raise_for_status()
                data = resp.json()

            current = data.get("current_condition", [{}])[0]
            temp = current.get("temp_C", "?")
            desc_cn = current.get("lang_zh", [{}])
            if isinstance(desc_cn, list) and desc_cn:
                weather_desc = desc_cn[0].get("value", "")
            else:
                weather_desc = current.get("weatherDesc", [{}])[0].get("value", "")
            humidity = current.get("humidity", "?")
            wind = current.get("windspeedKmph", "?")

            display = f"{city}当前天气：{weather_desc}，温度 {temp}°C，湿度 {humidity}%，风速 {wind}km/h"

            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"city": city, "temp": temp, "desc": weather_desc},
                display_text=display,
            )

        except Exception as e:
            logger.error(f"Weather API error: {e}")
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text=f"查询{city}天气失败",
            )

    def _extract_city(self, query: str) -> str:
        """Extract city name from query. Simple heuristic."""
        import re
        # Try to find city name patterns
        patterns = [
            r"(?:查|看|搜|问)(?:一下)?(.{2,6}?)(?:的)?(?:天气|气温|温度)",
            r"(.{2,6}?)(?:今天|明天|后天|这周|下周)?(?:的)?天气",
            r"天气.*?(?:在|是)(.{2,6})",
        ]
        for p in patterns:
            m = re.search(p, query)
            if m:
                city = m.group(1).strip()
                if city and len(city) <= 10:
                    return city
        return "上海"  # Default city
