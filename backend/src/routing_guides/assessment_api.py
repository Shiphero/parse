"""Explicit, preview-only Jev assessment requests."""
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
from routing_guides.models import AnalysisRun
from routing_guides.tasks import assess_guide_rules, dsn
from routing_guides.workflow_api import VersionedAction, RunView, required, guard, audit

router = APIRouter(prefix='/api', tags=['Rule assessment'])


class StartAssessment(VersionedAction):
    model: str = Field(default='', max_length=150)
    scope: Literal['sample', 'all', 'selected'] = 'sample'
    sample_size: int = Field(default=25, ge=1, le=100)
    rule_ids: list[UUID] = Field(default_factory=list, max_length=10000)
    resume: bool = False


def prepare_job(data: dict, body: StartAssessment, model: str) -> dict:
    job = data.get('assessment_job') or {}
    if job.get('status') in {'queued', 'running'}:
        raise HTTPException(409, 'An assessment is already running.')
    if (data.get('classification_job') or {}).get('status') in {'queued', 'running'}:
        raise HTTPException(409, 'Wait for classification to finish before assessing its results.')
    if body.resume:
        if job.get('status') != 'failed' or job.get('model') != model or job.get('prompt_version') != PROMPT_VERSION:
            raise HTTPException(409, 'Only a stopped assessment with the same model and assessment version can resume.')
        return {**job, 'status': 'queued', 'error': None, 'failed_rule_id': None, 'actor': body.actor}
    pending = [r for r in data['rules'] if r['status'] == 'pending']
    if body.scope == 'sample':
        selected = choose_sample(pending, body.sample_size)
    elif body.scope == 'all':
        selected = pending
    else:
        ids = {str(id) for id in body.rule_ids}
        selected = [r for r in pending if r['id'] in ids]
        if len(selected) != len(ids):
            raise HTTPException(409, 'Select only current pending rules from this draft.')
    if not selected:
        raise HTTPException(409, 'No pending rules are selected for assessment.')
    return new_assessment_job(selected, model, body.actor, body.scope)


@router.post('/analysis/{run_id}/assess')
async def start_assessment(run_id: UUID, body: StartAssessment):
    config = await connection('jev')
    model = body.model.strip() or config['model']
    if not model or not config['key']:
        raise HTTPException(422, 'Configure Jev and its model in Connections first.')
    # Job enqueue and preview selection commit together, just like classification.
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cursor = await conn.execute('SELECT status, version, payload FROM analysis_runs WHERE id=%s FOR UPDATE', (run_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, 'Analysis not found.')
        status, version, data = row
        if status != 'complete' or version != body.version:
            raise HTTPException(409, 'Refresh the completed draft before assessing.')
        job = prepare_job(data, body, model)
        data['assessment_job'] = job
        await conn.execute('UPDATE analysis_runs SET payload=%s::jsonb, version=version+1 WHERE id=%s', (json.dumps(data), run_id))
        await assess_guide_rules.configure(connection=conn, lock=f'assessment:{run_id}', queueing_lock=f'assessment:{run_id}').defer_async(run_id=str(run_id), job_id=job['id'])
    return {'status': 'queued', 'job_id': job['id'], 'total': job['total']}


@router.post('/analysis/{run_id}/cancel-assessment', response_model=RunView)
async def cancel_assessment(run_id: UUID, body: VersionedAction):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        guard(run, body.version)
        data = deepcopy(run.payload)
        job = data.get('assessment_job') or {}
        if job.get('status') not in {'queued', 'running', 'failed'}:
            raise HTTPException(409, 'No active assessment to stop.')
        job['status'] = 'cancelled'
        run.payload, run.version = data, run.version + 1
        audit(session, run.id, body.actor, 'assessment_cancelled', {'job_id': job['id']})
        return RunView.model_validate(run)
