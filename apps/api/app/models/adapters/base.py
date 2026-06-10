from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncIterator


class ModelAdapter(ABC):
    provider: str
    model_name: str

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        **kwargs,
    ) -> AsyncIterator[str]:
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        **kwargs,
    ) -> str:
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        ...
