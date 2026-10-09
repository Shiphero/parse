"""One-shot, serialized local migration entrypoint."""
from importlib.metadata import version
import subprocess

import psycopg

from routing_guides.config import get_settings


def main() -> None:
    dsn = get_settings().database_url.get_secret_value().replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(914821)")
        try:
            subprocess.run(["alembic", "upgrade", "head"], check=True)
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
