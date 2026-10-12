from procrastinate import App, PsycopgConnector

from routing_guides.config import get_settings

dsn = get_settings().database_url.get_secret_value().replace("postgresql+psycopg://", "postgresql://", 1)
task_queue = App(connector=PsycopgConnector(conninfo=dsn))


@task_queue.task(name="system.record_worker_activity")
async def record_worker_activity() -> None:
    """Maintenance task; document analysis tasks will be added in the next milestone."""
    from routing_guides.worker import record_heartbeat

    await record_heartbeat()


@task_queue.task(name="guides.prepare")
async def prepare_guide(guide_id: str) -> None:
    from uuid import UUID
    from routing_guides.documents import prepare_document

    await prepare_document(UUID(guide_id))


@task_queue.periodic(cron="* * * * *")
@task_queue.task(name="system.recover_stalled", queueing_lock="recover_stalled")
async def recover_stalled(timestamp: int) -> None:
    for job in await task_queue.job_manager.get_stalled_jobs():
        await task_queue.job_manager.retry_job(job)


@task_queue.task(name='guides.analyze')
async def analyze_guide(run_id: str) -> None:
    from uuid import UUID
    from routing_guides.analysis_jobs import run_analysis
    await run_analysis(UUID(run_id))


@task_queue.task(name='guides.classify_rules')
async def classify_guide_rules(run_id: str, job_id: str) -> None:
    from uuid import UUID
    from routing_guides.classification_jobs import run_classification
    await run_classification(UUID(run_id), job_id)
