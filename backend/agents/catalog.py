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
            CatalogModel(id="gpt-6.1-sol", label="GPT-6.1 Sol"),
            CatalogModel(id="gpt-5.1", label="GPT-5.1"),
        ),
    ),
    CatalogProvider(
        id=ModelProvider.ANTHROPIC,
        label="Anthropic",
        models=(CatalogModel(id="claude-opus-5-5", label="Claude Opus 5.5"),),
    ),
    CatalogProvider(
        id=ModelProvider.GOOGLE,
        label="Google",
        models=(CatalogModel(id="gemini-3.8-flash", label="Gemini 3.8 Flash"),),
    ),
    CatalogProvider(
        id=ModelProvider.XAI,
        label="xAI",
        models=(CatalogModel(id="grok-4.7", label="Grok 4.7"),),
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
