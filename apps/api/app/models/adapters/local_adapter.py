from app.models.adapters.openai_adapter import OpenAICompatibleAdapter


def create_local_adapter(
    model_name: str,
    base_url: str = "http://localhost:8080/v1",
    max_tokens: int = 2048,
    temperature: float = 0.8,
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        provider="local",
        model_name=model_name,
        api_key="not-needed",
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
    )
