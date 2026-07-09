from __future__ import annotations

import logging
import re

import httpx

from app.tools.base import ToolBase, ToolResult

logger = logging.getLogger(__name__)


class SearchTool(ToolBase):
    name = "search"
    description = "搜索网络获取信息"
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
    }

    async def execute(self, params: dict) -> ToolResult:
        query = params.get("query", "")
        search_query = self._extract_search_query(query)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": search_query},
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; CompanionBot/1.0)",
                    },
                )
                resp.raise_for_status()

            # Parse results from HTML (simple extraction)
            results = self._parse_results(resp.text)

            if results:
                display_parts = []
                for i, r in enumerate(results[:3], 1):
                    display_parts.append(f"{i}. {r['title']}: {r['snippet']}")
                display = "\n".join(display_parts)
            else:
                display = f"搜索「{search_query}」未找到结果"

            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"query": search_query, "results": results[:3]},
                display_text=display,
            )

        except Exception as e:
            logger.error(f"Search error: {e}")
            return ToolResult(
                tool_name=self.name,
                status="failed",
                display_text="搜索失败",
            )

    def _extract_search_query(self, query: str) -> str:
        """Extract search keywords from natural language."""
        # Remove common prefixes
        for prefix in ["帮我搜", "搜索", "搜一下", "查一下", "帮我查", "帮我找", "百度", "谷歌"]:
            query = query.replace(prefix, "")
        return query.strip() or "AI Companion"

    def _parse_results(self, html: str) -> list[dict]:
        """Simple HTML parsing for DuckDuckGo results."""
        results = []
        # Find result blocks
        title_pattern = re.compile(r'class="result__a"[^>]*>([^<]+)</a>')
        snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</span>', re.DOTALL)

        titles = title_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for title, snippet in zip(titles, snippets):
            # Clean HTML tags from snippet
            clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
            if title and clean_snippet:
                results.append({
                    "title": title.strip(),
                    "snippet": clean_snippet[:200],
                })
        return results
