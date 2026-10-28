"""Local-only credential persistence. Secrets never appear in API responses or logs."""
import json
import os
import tempfile
from routing_guides.config import get_settings
from routing_guides.app_settings import setting, save_setting

NAMES = {'anthropic', 'openai', 'litellm', 'jev', 'shiphero'}


async def connection(name: str) -> dict:
    if name not in NAMES:
        raise ValueError('Unknown connection.')
    settings = get_settings()
    path = settings.storage_root / 'connections.json'
    stored = json.loads(path.read_text()) if settings.credentials_mode == 'local' and path.exists() else {}
    local = stored.get(name, {}) if settings.credentials_mode == 'local' else {}
    if name == 'shiphero':
        return {'key': local.get('key', os.environ.get('SHIPHERO_ACCESS_TOKEN', '')), 'model': ''}
    config = {'key': local.get('key', getattr(settings, f'{name}_api_key').get_secret_value()),
              'model': await setting(f'{name}.model', getattr(settings, f'{name}_model'))}
    if name == 'litellm':
        config['base_url'] = settings.litellm_base_url
    return config


async def save_connection(name: str, key: str | None, model: str) -> None:
    if name not in NAMES:
        raise ValueError('Unknown connection.')
    if get_settings().credentials_mode == 'environment' and key is not None:
        raise ValueError('Credentials are managed by the deployment. Update them in Secrets Manager.')
    if name != 'shiphero':
        await save_setting(f'{name}.model', model.strip())
    if key is None:
        return
    folder = get_settings().storage_root
    path = folder / 'connections.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    data[name] = {'key': key.strip()}
    fd, temporary = tempfile.mkstemp(prefix='.connections-', dir=folder)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def statuses() -> list[dict]:
    result = []
    for name in ('anthropic', 'openai', 'litellm', 'jev', 'shiphero'):
        config = await connection(name)
        result.append({'id': name, 'credential_configured': bool(config['key']), 'model': config['model'],
                       'credential_managed': get_settings().credentials_mode == 'environment',
                       'base_url': config.get('base_url')})
    return result
