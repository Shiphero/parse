import asyncio
from contextlib import suppress
import logging

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from routing_guides.db import engine, sessions
from routing_guides.models import ServiceHeartbeat
from routing_guides.tasks import task_queue


async def record_heartbeat() -> None:
    statement = insert(ServiceHeartbeat).values(service="worker", last_seen=func.now())
    async with sessions.begin() as session:
        await session.execute(statement.on_conflict_do_update(
            index_elements=[ServiceHeartbeat.service], set_={"last_seen": func.now()},
        ))


async def heartbeat_loop() -> None:
    while True:
        await record_heartbeat()
        await asyncio.sleep(15)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with task_queue.open_async():
        worker = asyncio.create_task(task_queue.run_worker_async(concurrency=2))
        heartbeat = asyncio.create_task(heartbeat_loop())
        try:
            done, _ = await asyncio.wait([worker, heartbeat], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in (worker, heartbeat):
                task.cancel()
            for task in (worker, heartbeat):
                with suppress(asyncio.CancelledError):
                    await task
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
