from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import BaseModel


class AnalyzerInput(BaseModel):
    user_id: str
    session_id: str
    message: str
    trace_id: str


class IntentResult(BaseModel):
    primary_intent: str          # emotional_support / task / chitchat / question
    secondary_intents: list[str] = []
    confidence: float = 0.0
    tool_needs: list[str] = []


class EmotionResult(BaseModel):
    emotion: str = "neutral"     # joy / sadness / anger / fear / fatigue / neutral / anxiety
    intensity: float = 0.0       # 0-1
    valence: float = 0.0         # -1 (negative) ~ +1 (positive)
    trend: str = "stable"        # improving / stable / declining


class RiskResult(BaseModel):
    level: str = "low"           # low / medium / high / critical
    category: str = "none"       # scam_alert / health_emergency / emotional_crisis / emotional_low / none
    confidence: float = 0.0
    triggered_rules: list[str] = []


class MemorySnapshot(BaseModel):
    working: list[dict] = []     # L0: recent messages
    summary: str | None = None   # L1: session summary
    profile: dict = {}           # L2: user profile
    vectors: list[dict] = []     # L3: recalled memories


class PersonalityConfig(BaseModel):
    tone: str = "warm, natural"
    style_rules: list[str] = []
    max_length: int | None = None
    avoid_phrases: list[str] = []
    encourage_patterns: list[str] = []


class UserProfile(BaseModel):
    user_id: str
    profile_json: dict = {}
    version: int = 1


class BaseEngine(ABC):
    @abstractmethod
    async def analyze(self, input: AnalyzerInput) -> BaseModel:
        ...
