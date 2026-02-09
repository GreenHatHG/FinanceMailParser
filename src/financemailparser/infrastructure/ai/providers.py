"""
AI provider helpers.

This module centralizes:
- Supported provider identifiers used across config/service/UI
- Common rules for building litellm model names (provider prefixing)
"""

from __future__ import annotations


AI_PROVIDER_OPENAI = "openai"
AI_PROVIDER_GEMINI = "gemini"
AI_PROVIDER_ANTHROPIC = "anthropic"
AI_PROVIDER_AZURE = "azure"
AI_PROVIDER_CUSTOM = "custom"

# Provider choices shown in UI and stored in config.yaml.
AI_PROVIDER_CHOICES: tuple[str, ...] = (
    AI_PROVIDER_OPENAI,
    AI_PROVIDER_GEMINI,
    AI_PROVIDER_ANTHROPIC,
    AI_PROVIDER_AZURE,
    AI_PROVIDER_CUSTOM,
)

# Providers that expect/accept a "{provider}/{model}" form in litellm.
AI_PROVIDERS_WITH_PREFIX: set[str] = {
    AI_PROVIDER_OPENAI,
    AI_PROVIDER_GEMINI,
    AI_PROVIDER_ANTHROPIC,
    AI_PROVIDER_AZURE,
}


def ensure_litellm_model_prefix(provider: str | None, model: str | None) -> str | None:
    """
    Ensure model name uses litellm's explicit provider prefix when appropriate.

    Examples:
    - provider=openai, model=gpt-4o -> openai/gpt-4o
    - provider=openai, model=openai/gpt-4o -> openai/gpt-4o
    - provider=custom, model=org/model -> org/model
    """
    if model is None:
        return None

    model = str(model).strip()
    if not model:
        return model

    provider = str(provider or "").strip()
    if provider in AI_PROVIDERS_WITH_PREFIX:
        prefix = f"{provider}/"
        if not model.startswith(prefix):
            return f"{prefix}{model}"
    return model


def strip_litellm_model_prefix(provider: str | None, model: str | None) -> str | None:
    """
    Strip "{provider}/" prefix from model for token_counter or display usage.

    This mirrors the behavior in ui/streamlit/pages/ai/process_beancount.py.
    """
    if model is None:
        return None

    model = str(model).strip()
    if not model:
        return model

    provider = str(provider or "").strip()
    if provider in AI_PROVIDERS_WITH_PREFIX:
        prefix = f"{provider}/"
        if model.startswith(prefix):
            return model[len(prefix) :]
    return model
