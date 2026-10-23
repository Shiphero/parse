"""One-shot, serialized local migration entrypoint."""
from importlib.metadata import version
import subprocess
import json
from psycopg.types.json import Jsonb

import psycopg

from routing_guides.config import get_settings


def main() -> None:
    dsn = get_settings().database_url.get_secret_value().replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(914821)")
        try:
            subprocess.run(["alembic", "upgrade", "head"], check=True)
            # Import only non-secret preferences; never copy credentials into PostgreSQL.
            settings = get_settings()
            path = settings.storage_root / 'connections.json'
            legacy = json.loads(path.read_text()) if path.exists() else {}
            defaults = {'max_upload_mb': settings.max_upload_mb}
            for provider in ('anthropic', 'openai', 'jev'):
                defaults[f'{provider}.model'] = legacy.get(provider, {}).get('model', getattr(settings, f'{provider}_model'))
            for name, value in defaults.items():
                connection.execute('INSERT INTO application_settings(name,value) VALUES (%s,%s) ON CONFLICT(name) DO NOTHING',
                                   (name, Jsonb({'value': value})))
            connection.execute("CREATE TABLE IF NOT EXISTS queue_schema_version (singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), version text NOT NULL)")
            row = connection.execute("SELECT version FROM queue_schema_version WHERE singleton = true").fetchone()
            installed = version("procrastinate")
            if row is None:
                subprocess.run(["procrastinate", "--app=routing_guides.tasks.task_queue", "schema", "--apply"], check=True)
                connection.execute("INSERT INTO queue_schema_version (version) VALUES (%s)", (installed,))
            elif row[0] != installed:
                raise RuntimeError("Queue dependency changed. Apply its documented SQL migrations and update queue_schema_version before startup.")
        finally:
            connection.execute("SELECT pg_advisory_unlock(914821)")


if __name__ == "__main__":
    main()
