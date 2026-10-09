from typing import Literal

from pydantic import BaseModel

from routing_guides.config import get_settings


class ProviderStatus(BaseModel):
    id: str
    name: str
    credential_configured: bool
    model: str | None
    implementation: Literal["planned"] = "planned"
    connection_verified: bool = False


def provider_statuses() -> list[ProviderStatus]:
    settings = get_settings()
    return [
        ProviderStatus(
            id="anthropic", name="Claude",
            credential_configured=bool(settings.anthropic_api_key.get_secret_value()),
            model=settings.anthropic_model or None,
        ),
        ProviderStatus(
            id="openai", name="OpenAI",
            credential_configured=bool(settings.openai_api_key.get_secret_value()),
            model=settings.openai_model or None,
        ),
    ]
