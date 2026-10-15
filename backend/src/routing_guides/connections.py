"""Local-only credential persistence. Secrets never appear in API responses or logs."""
import json
import os
import tempfile
from routing_guides.config import get_settings

NAMES = {'anthropic', 'openai', 'jev', 'shiphero'}


def connection(name: str) -> dict:
    if name not in NAMES:
        raise ValueError('Unknown connection.')
    settings = get_settings()
    path = settings.storage_root / 'connections.json'
    stored = json.loads(path.read_text()) if path.exists() else {}
    if name in stored:
        return stored[name]
    if name == 'shiphero':
        return {'key': os.environ.get('SHIPHERO_ACCESS_TOKEN', ''), 'model': ''}
    return {'key': getattr(settings, f'{name}_api_key').get_secret_value(), 'model': getattr(settings, f'{name}_model')}


def save_connection(name: str, key: str | None, model: str) -> None:
    if name not in NAMES:
        raise ValueError('Unknown connection.')
    folder = get_settings().storage_root
    path = folder / 'connections.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    data[name] = {'key': connection(name)['key'] if key is None else key.strip(), 'model': model.strip()}
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


def statuses() -> list[dict]:
    return [{'id': name, 'credential_configured': bool(connection(name)['key']), 'model': connection(name)['model']} for name in ('anthropic', 'openai', 'jev', 'shiphero')]
