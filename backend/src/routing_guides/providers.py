from typing import Literal

from pydantic import BaseModel

from routing_guides.connections import connection


class ProviderStatus(BaseModel):
    id: str
    name: str
    credential_configured: bool
    model: str | None
    implementation: Literal["implemented"] = "implemented"
    connection_verified: bool = False


async def provider_statuses() -> list[ProviderStatus]:
    anthropic, openai, litellm = await connection("anthropic"), await connection("openai"), await connection("litellm")
    return [
        ProviderStatus(
            id="anthropic", name="Claude",
            credential_configured=bool(anthropic["key"]),
            model=anthropic["model"] or None,
        ),
        ProviderStatus(
            id="openai", name="OpenAI",
            credential_configured=bool(openai["key"]),
            model=openai["model"] or None,
        ),
        ProviderStatus(id="litellm", name="LiteLLM", credential_configured=bool(litellm['key']), model=litellm['model'] or None),
    ]
