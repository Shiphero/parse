"""Explicit OpenAI-compatible gateway routing; never fall back to a direct provider."""
from urllib.parse import urlsplit

import httpx
from openai import AsyncOpenAI


def compact_gateway_schema(schema):
    """Keep structure strict; enforce collection/string bounds in local Pydantic validation.

    Gemini rejects the correction schema's combined length bounds with INVALID_ARGUMENT.
    Removing those generation constraints avoids the rejection without accepting an
    oversized or invalid proposal: the complete ResolutionPlan still validates locally.
    """
    if isinstance(schema, dict):
        return {key: compact_gateway_schema(value) for key, value in schema.items()
                if key not in {'minItems', 'maxItems', 'minLength', 'maxLength'}}
    if isinstance(schema, list):
        return [compact_gateway_schema(value) for value in schema]
    return schema


def openai_options(provider: str, config: dict) -> dict:
    options = {'api_key': config['key'], 'timeout': 180, 'max_retries': 0}
    if provider == 'litellm':
        endpoint = config.get('base_url', '').strip().rstrip('/')
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError('Configure LITELLM_BASE_URL as an HTTPS gateway URL without credentials, query parameters or fragments.')
        options.update(base_url=endpoint, http_client=httpx.AsyncClient(follow_redirects=False))
    elif provider != 'openai':
        raise ValueError('Unsupported model connection.')
    return options


async def gateway_models(config: dict) -> list[str]:
    """Return only the model aliases available to this key; no paid generation."""
    if not config['key']:
        raise ValueError('Configure the LiteLLM key before loading models.')
    async with AsyncOpenAI(**openai_options('litellm', config)) as client:
        models = await client.models.list()
        return sorted({model.id async for model in models})
