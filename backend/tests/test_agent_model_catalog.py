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
                    {"id": "gpt-6.1-sol", "label": "GPT-6.1 Sol"},
                    {"id": "gpt-5.1", "label": "GPT-5.1"},
                ],
            },
            {
                "id": ModelProvider.ANTHROPIC,
                "label": "Anthropic",
                "models": [{"id": "claude-opus-5-5", "label": "Claude Opus 5.5"}],
            },
            {
                "id": ModelProvider.GOOGLE,
                "label": "Google",
                "models": [{"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"}],
            },
            {
                "id": ModelProvider.XAI,
                "label": "xAI",
                "models": [{"id": "grok-4.7", "label": "Grok 4.7"}],
            },
        ]
    }
    assert len(MODEL_CATALOG) == 4


def test_model_catalog_accepts_seeded_default_and_rejects_unknown_pairs() -> None:
    assert supports_model(ModelProvider.OPENAI, "gpt-6.1-sol")
    assert supports_model("xai", "grok-4.7")
    assert not supports_model(ModelProvider.OPENAI, "unapproved-model")
    assert not supports_model(ModelProvider.XAI, "gpt-5.1")
