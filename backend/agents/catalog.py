"""The supported provider/model pairs exposed by the agent configuration API."""

from __future__ import annotations

from dataclasses import dataclass

from db.types import ModelProvider


@dataclass(frozen=True)
class CatalogModel:
    id: str
    label: str


@dataclass(frozen=True)
class CatalogProvider:
    id: ModelProvider
    label: str
    models: tuple[CatalogModel, ...]


MODEL_CATALOG: tuple[CatalogProvider, ...] = (
    CatalogProvider(
        id=ModelProvider.OPENAI,
        label="OpenAI",
        models=(
            CatalogModel(id="gpt-6-astra", label="GPT-6 Astra"),
            CatalogModel(id="gpt-6.1-sol", label="GPT-6.1 Sol"),
            CatalogModel(id="gpt-6.1-terra", label="GPT-6.1 Terra"),
            CatalogModel(id="gpt-6-luna", label="GPT-6 Luna"),
            CatalogModel(id="gpt-5.1", label="GPT-5.1"),
        ),
    ),
    CatalogProvider(
        id=ModelProvider.ANTHROPIC,
        label="Anthropic",
        models=(
            CatalogModel(id="claude-fable-5-1", label="Claude Fable 5.1"),
            CatalogModel(id="claude-opus-5-5", label="Claude Opus 5.5"),
            CatalogModel(id="claude-sonnet-5-5", label="Claude Sonnet 5.5"),
            CatalogModel(id="claude-haiku-5-5", label="Claude Haiku 5.5"),
        ),
    ),
    CatalogProvider(
        id=ModelProvider.GOOGLE,
        label="Google",
        models=(
            CatalogModel(id="gemini-4-argon", label="Gemini 4 Argon"),
            CatalogModel(id="gemini-3.8-flash", label="Gemini 3.8 Flash"),
            CatalogModel(id="gemini-3.6-flash", label="Gemini 3.6 Flash"),
            CatalogModel(id="gemini-3.5-flash-lite", label="Gemini 3.5 Flash-Lite"),
            CatalogModel(id="gemini-3.1-flash-lite", label="Gemini 3.1 Flash-Lite"),
            CatalogModel(id="gemini-2.5-pro", label="Gemini 2.5 Pro"),
            CatalogModel(id="gemini-2.5-flash", label="Gemini 2.5 Flash"),
        ),
    ),
    CatalogProvider(
        id=ModelProvider.XAI,
        label="xAI",
        models=(
            CatalogModel(id="grok-4.7", label="Grok 4.7"),
            CatalogModel(id="grok-4.6", label="Grok 4.6"),
            CatalogModel(id="grok-4.5", label="Grok 4.5"),
            CatalogModel(id="grok-4.3", label="Grok 4.3"),
            CatalogModel(
                id="grok-4.20-0309-reasoning",
                label="Grok 4.20 Reasoning",
            ),
            CatalogModel(
                id="grok-4.20-0309-non-reasoning",
                label="Grok 4.20 Non-Reasoning",
            ),
            CatalogModel(
                id="grok-4.20-multi-agent-0309",
                label="Grok 4.20 Multi-Agent",
            ),
        ),
    ),
)


def supports_model(provider: ModelProvider | str, model_name: str) -> bool:
    provider_value = provider.value if isinstance(provider, ModelProvider) else provider
    return any(
        item.id.value == provider_value
        and any(model.id == model_name for model in item.models)
        for item in MODEL_CATALOG
    )


def model_catalog_response() -> dict[str, object]:
    return {
        "providers": [
            {
                "id": provider.id,
                "label": provider.label,
                "models": [
                    {"id": model.id, "label": model.label} for model in provider.models
                ],
            }
            for provider in MODEL_CATALOG
        ]
    }


__all__ = [
    "MODEL_CATALOG",
    "CatalogModel",
    "CatalogProvider",
    "model_catalog_response",
    "supports_model",
]
