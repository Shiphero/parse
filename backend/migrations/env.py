import asyncio

from alembic import context

from routing_guides.db import Base, engine
from routing_guides import models  # noqa: F401


def apply_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run():
    async with engine.connect() as connection:
        await connection.run_sync(apply_migrations)
    await engine.dispose()


asyncio.run(run())
