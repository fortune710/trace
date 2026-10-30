from agents.catalog import MODEL_CATALOG, model_catalog_response, supports_model
from db.types import ModelProvider


def test_model_catalog_exposes_only_supported_provider_model_pairs() -> None:
    response = model_catalog_response()

    assert response == {
        "providers": [
            {
                "id": ModelProvider.OPENAI,
                "label": "OpenAI",
                "models": [
                    {"id": "gpt-6-astra", "label": "GPT-6 Astra"},
                    {"id": "gpt-6.1-sol", "label": "GPT-6.1 Sol"},
                    {"id": "gpt-6.1-terra", "label": "GPT-6.1 Terra"},
                    {"id": "gpt-6-luna", "label": "GPT-6 Luna"},
                    {"id": "gpt-5.1", "label": "GPT-5.1"},
                ],
            },
            {
                "id": ModelProvider.ANTHROPIC,
                "label": "Anthropic",
                "models": [
                    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1"},
                    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5"},
                    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
                    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5"},
                ],
            },
            {
                "id": ModelProvider.GOOGLE,
                "label": "Google",
                "models": [
                    {"id": "gemini-4-argon", "label": "Gemini 4 Argon"},
                    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
                    {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash"},
                    {
                        "id": "gemini-3.5-flash-lite",
                        "label": "Gemini 3.5 Flash-Lite",
                    },
                    {
                        "id": "gemini-3.1-flash-lite",
                        "label": "Gemini 3.1 Flash-Lite",
                    },
                    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
                    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
                ],
            },
            {
                "id": ModelProvider.XAI,
                "label": "xAI",
                "models": [
                    {"id": "grok-4.7", "label": "Grok 4.7"},
                    {"id": "grok-4.6", "label": "Grok 4.6"},
                    {"id": "grok-4.5", "label": "Grok 4.5"},
                    {"id": "grok-4.3", "label": "Grok 4.3"},
                    {
                        "id": "grok-4.20-0309-reasoning",
                        "label": "Grok 4.20 Reasoning",
                    },
                    {
                        "id": "grok-4.20-0309-non-reasoning",
                        "label": "Grok 4.20 Non-Reasoning",
                    },
                    {
                        "id": "grok-4.20-multi-agent-0309",
                        "label": "Grok 4.20 Multi-Agent",
                    },
                ],
            },
        ]
    }
    assert len(MODEL_CATALOG) == 4


def test_model_catalog_accepts_seeded_default_and_rejects_unknown_pairs() -> None:
    assert supports_model(ModelProvider.OPENAI, "gpt-6.1-sol")
    assert supports_model(ModelProvider.ANTHROPIC, "claude-sonnet-5-5")
    assert supports_model(ModelProvider.GOOGLE, "gemini-4-argon")
    assert supports_model("xai", "grok-4.7")
    assert not supports_model(ModelProvider.OPENAI, "unapproved-model")
    assert not supports_model(ModelProvider.XAI, "gpt-5.1")
