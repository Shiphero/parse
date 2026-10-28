"""Explicit requests to prepare pending rules and assess their review readiness."""
from copy import deepcopy
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field
import psycopg
from routing_guides.assessment import PROMPT_VERSION, choose_sample, new_assessment_job
from routing_guides.connections import connection
from routing_guides.db import sessions
from routing_guides.resolution_jobs import enable_resolution
from routing_guides.resolution import RESOLUTION_VERSION
from routing_guides.review_processing import now
from routing_guides.models import AnalysisRun
from routing_guides.tasks import assess_guide_rules, dsn
from routing_guides.workflow_api import VersionedAction, RunView, required, guard, audit

router = APIRouter(prefix='/api', tags=['Rule assessment'])


class StartAssessment(VersionedAction):
    model: str = Field(default='', max_length=150)
    scope: Literal['sample', 'all', 'selected', 'failed'] = 'sample'
    sample_size: int = Field(default=25, ge=1, le=100)
    rule_ids: list[UUID] = Field(default_factory=list, max_length=10000)
    resume: bool = False
    auto_process: bool = True
    preparation_provider: Literal['anthropic', 'openai', 'litellm'] | None = None
    preparation_model: str = Field(default='', max_length=150)


class CancelAssessment(VersionedAction):
    job_id: UUID | None = None


def prepare_job(data: dict, body: StartAssessment, model: str) -> dict:
    job = data.get('assessment_job') or {}
    if job.get('status') in {'queued', 'running'}:
        raise HTTPException(409, 'An assessment is already running.')
    if (data.get('classification_job') or {}).get('status') in {'queued', 'running'}:
        raise HTTPException(409, 'Wait for classification to finish before assessing its results.')
    if body.resume:
        if ((body.preparation_provider and body.preparation_provider != job.get('resolution_provider'))
                or (body.preparation_model.strip() and body.preparation_model.strip() != job.get('resolution_model'))):
            raise HTTPException(409, 'Start a new review to change its model connection. Completed compatible work will be reused.')
        if (job.get('status') not in {'failed', 'cancelled'} or job.get('model') != model
                or job.get('prompt_version') != PROMPT_VERSION
                or job.get('resolution_version', RESOLUTION_VERSION) != RESOLUTION_VERSION):
            raise HTTPException(409, 'Only a stopped assessment with the same model and assessment version can resume.')
        return {**job, 'status': 'queued', 'error': None, 'reason': None, 'failed_rule_id': None,
                'recent_preparation_failures': [], 'actor': body.actor, 'updated_at': now()}
    pending = [r for r in data['rules'] if r['status'] == 'pending']
    if body.scope == 'sample':
        selected = choose_sample(pending, body.sample_size)
    elif body.scope == 'all':
        selected = pending
    elif body.scope == 'failed':
        if job.get('pending') and job.get('status') != 'cancelled':
            raise HTTPException(409, 'Continue or stop the unfinished checks before retrying failed rules.')
        selected = [r for r in pending if (r.get('assessment') or {}).get('check_failed') or
                    ((r.get('resolution') or {}).get('failed') and r['resolution'].get('revision') == r['revision'])]
        if not selected:
            raise HTTPException(409, 'No failed checks remain on pending rules.')
    else:
        ids = {str(id) for id in body.rule_ids}
        selected = [r for r in pending if r['id'] in ids]
        if len(selected) != len(ids):
            raise HTTPException(409, 'Select only current pending rules from this draft.')
    if not selected:
        raise HTTPException(409, 'No pending rules are selected for assessment.')
    return {**new_assessment_job(selected, model, body.actor, body.scope), 'auto_process': body.auto_process}


@router.post('/analysis/{run_id}/assess')
async def start_assessment(run_id: UUID, body: StartAssessment):
    config = await connection('jev')
    model = body.model.strip() or config['model']
    if not model or not config['key']:
        raise HTTPException(422, 'Configure Jev and its model in Connections first.')
    # Job enqueue and rule selection commit together, just like classification.
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cursor = await conn.execute('SELECT status, version, payload, config FROM analysis_runs WHERE id=%s FOR UPDATE', (run_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, 'Analysis not found.')
        status, version, data, run_config = row
        if status != 'complete' or version != body.version:
            raise HTTPException(409, 'Refresh the completed draft before assessing.')
        job = prepare_job(data, body, model)
        if not body.resume:
            try:
                resolution_config = run_config
                if body.preparation_provider:
                    selected = await connection(body.preparation_provider)
                    resolution_config = {'provider': body.preparation_provider,
                        'model': body.preparation_model.strip() or selected['model']}
                elif body.preparation_model.strip():
                    raise ValueError('Choose a model connection when specifying a preparation model.')
                await enable_resolution(job, resolution_config)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        data['assessment_job'] = job
        await conn.execute('UPDATE analysis_runs SET payload=%s::jsonb, version=version+1 WHERE id=%s', (json.dumps(data), run_id))
        await assess_guide_rules.configure(connection=conn, lock=f'assessment:{run_id}', queueing_lock=f'assessment:{run_id}').defer_async(run_id=str(run_id), job_id=job['id'])
    return {'status': 'queued', 'job_id': job['id'], 'total': job['total']}


@router.post('/analysis/{run_id}/cancel-assessment', response_model=RunView)
async def cancel_assessment(run_id: UUID, body: CancelAssessment):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        data = deepcopy(run.payload)
        job = data.get('assessment_job') or {}
        if body.job_id is not None:
            if str(body.job_id) != job.get('id'):
                raise HTTPException(409, 'A different review run has started. Refresh before stopping it.')
            # Saving another rule must not make the Stop button race against progress.
            guard(run, run.version)
        else:
            guard(run, body.version)
        if job.get('status') not in {'queued', 'running', 'failed'}:
            raise HTTPException(409, 'No active assessment to stop.')
        job['status'] = 'cancelled'
        job['updated_at'] = now()
        run.payload, run.version = data, run.version + 1
        audit(session, run.id, body.actor, 'assessment_cancelled', {'job_id': job['id']})
        return RunView.model_validate(run)
