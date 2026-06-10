from app.models.adapters.openai_adapter import OpenAICompatibleAdapter


def create_qwen_adapter(
    model_name: str,
    api_key: str,
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    max_tokens: int = 2048,
    temperature: float = 0.8,
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        provider="qwen",
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
    )
