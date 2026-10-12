from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, computed_field, field_validator, model_validator, PrivateAttr
import psycopg
from sqlalchemy import select
from routing_guides.analysis_jobs import validate_evidence
from routing_guides.analysis_provider import PROMPT_VERSION
from routing_guides.connections import connection, statuses, save_connection
from routing_guides.db import sessions
from routing_guides.evaluator import evaluate_release
from routing_guides.models import AnalysisRun, AuditEvent, Evaluation, Guide, GuidePage, ReleaseHead, RuleRelease, Scenario
from routing_guides.review import compare_rules, duplicate_titles, individual_review_reasons
from routing_guides.rules import RuleSpec, PageCoverage, EvaluationItem
from routing_guides.scenarios import normalize, MAPPING_VERSION
from routing_guides.shiphero import fetch_order
from routing_guides.tasks import analyze_guide, dsn

router = APIRouter(prefix='/api', tags=['Rules and scenarios'])


class Candidate(BaseModel):
    id: str
    revision: int
    status: Literal['pending', 'approved', 'rejected']
    spec: RuleSpec
    source_guide_id: str
    review: dict[str, Any] | None = None
    evidence_issues: list[str] = Field(default_factory=list)
    carried_from_release_id: str | None = None
    carried_from_rule_id: str | None = None

    _duplicate: bool = PrivateAttr(default=False)

    @computed_field
    @property
    def individual_review_reasons(self) -> list[str]:
        return individual_review_reasons(self.spec, self.evidence_issues, self._duplicate)


class RunPayload(BaseModel):
    rules: list[Candidate] = []
    coverage: list[PageCoverage] = []
    warnings: list[str] = []
    batches: list[dict[str, Any]] = []
    pending_batches: list[list[int]] = []


    @model_validator(mode='after')
    def flag_duplicates(self):
        duplicates = duplicate_titles([{'spec': {'title': r.spec.title}, 'status': r.status} for r in self.rules])
        for rule in self.rules:
            rule._duplicate = rule.status != 'rejected' and rule.spec.title.strip().casefold() in duplicates
        return self


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    guide_id: UUID
    version: int
    status: str
    config: dict[str, Any]
    payload: RunPayload
    error: str | None
    created_at: datetime


class ReleaseRule(BaseModel):
    stable_id: str
    spec: RuleSpec
    source_guide_id: str
    draft_id: str
    review: dict[str, Any]


class ReleasePayload(BaseModel):
    rules: list[ReleaseRule]
    base_release_id: str | None
    decisions: dict[str, str]
    scope: str
    coverage_note: str
    actor: str
    run_version: int


class ReleaseView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    retailer_id: str
    run_id: UUID
    name: str
    effective_date: date
    payload: ReleasePayload
    created_at: datetime


class ConnectionView(BaseModel):
    id: str
    credential_configured: bool
    model: str


class WorkflowView(BaseModel):
    runs: list[RunView]
    releases: list[ReleaseView]
    active_release_id: UUID | None
    connections: list[ConnectionView]


class StartAnalysis(BaseModel):
    provider: Literal['anthropic', 'openai', 'manual'] = 'anthropic'
    model: str = Field(default='', max_length=150)
    batch_pages: int = Field(default=12, ge=1, le=50)
    request_id: UUID


class VersionedAction(BaseModel):
    version: int
    actor: str = Field(min_length=1, max_length=200)
    note: str = Field(default='', max_length=5000)


    @field_validator('actor')
    @classmethod
    def named_reviewer(cls, value):
        if not value.strip():
            raise ValueError('Enter your reviewer name.')
        return value.strip()


class BulkApproval(VersionedAction):
    revisions: dict[UUID, int] = Field(min_length=1, max_length=1000)


class CarryApprovals(VersionedAction):
    base_release_id: UUID
    scope_confirmed: bool


class ComparisonView(BaseModel):
    base_release_id: UUID | None = None
    base_name: str = ''
    base_scope: str = ''
    unchanged: dict[str, str] = Field(default_factory=dict)
    changed: dict[str, list[str]] = Field(default_factory=dict)
    added: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class ReviewAction(VersionedAction):
    action: Literal['save', 'approve', 'reject']
    spec: RuleSpec | None = None


class AddRule(VersionedAction):
    spec: RuleSpec


class CoverageAction(VersionedAction):
    page: int = Field(ge=1)
    outcome: Literal['rules_found', 'no_rules']


class PublishAction(VersionedAction):
    name: str = Field(min_length=1, max_length=200)
    effective_date: date
    base_release_id: UUID | None = None
    decisions: dict[str, str] = Field(default_factory=dict)
    scope: str = Field(min_length=1, max_length=5000)
    coverage_confirmed: bool
    impact_confirmed: bool


class RestoreAction(BaseModel):
    expected_active_id: UUID | None
    actor: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=5000)


class ConnectionAction(BaseModel):
    key: SecretStr | None = None
    model: str = Field(default='', max_length=150)


class ScenarioCreate(BaseModel):
    retailer_id: str
    name: str = Field(min_length=1, max_length=200)
    raw: dict[str, Any]
    overrides: dict[str, Any] = Field(default_factory=dict)


class ScenarioView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    retailer_id: str
    name: str
    payload: dict[str, Any]
    created_at: datetime


class EvaluationView(BaseModel):
    id: UUID
    scenario_id: UUID
    release_id: UUID
    evaluator_version: str
    items: list[EvaluationItem]
    counts: dict[str, int]
    created_at: datetime


class ShipHeroRequest(BaseModel):
    retailer_id: str
    order_id: str = Field(min_length=1, max_length=200)


async def required(session, model, id, lock=False):
    obj = await session.get(model, id, with_for_update=lock)
    if obj is None:
        raise HTTPException(404, 'Record not found.')
    return obj


def audit(session, id, actor, action, payload):
    session.add(AuditEvent(id=uuid4(), entity_id=id, actor=actor.strip(), action=action, payload=payload))


def guard(run, version):
    if run.version != version:
        raise HTTPException(409, 'This draft changed. Refresh and review the latest revision.')
    if run.status != 'complete':
        raise HTTPException(409, 'Only a completed, unpublished analysis can be edited or published.')


async def check_evidence(session, run, spec):
    pages = (await session.scalars(select(GuidePage).where(GuidePage.guide_id == run.guide_id))).all()
    try:
        validate_evidence(spec, {p.page_index+1: p.text for p in pages})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/connections', response_model=list[ConnectionView])
async def connections():
    return statuses()


@router.put('/connections/{provider}', response_model=list[ConnectionView])
async def update_connection(provider: Literal['anthropic', 'openai', 'shiphero'], body: ConnectionAction, request: Request):
    # Custom header disallows browser cross-origin form submissions; no CORS is enabled.
    if request.headers.get('X-Requested-With') != 'routing-guide-parser':
        raise HTTPException(403, 'Use the local application to update connections.')
    # Serialize all credential updates across API processes; write atomically with mode 0600.
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute('SELECT pg_advisory_xact_lock(914822)')
        save_connection(provider, body.key.get_secret_value() if body.key is not None else None, body.model)
    return statuses()


@router.get('/guides/{guide_id}/workflow', response_model=WorkflowView)
async def workflow(guide_id: UUID):
    async with sessions() as session:
        guide = await required(session, Guide, guide_id)
        runs = (await session.scalars(select(AnalysisRun).where(AnalysisRun.guide_id == guide_id).order_by(AnalysisRun.created_at.desc()))).all()
        releases = (await session.scalars(select(RuleRelease).where(RuleRelease.retailer_id == guide.retailer_id).order_by(RuleRelease.created_at.desc()))).all()
        head = await session.get(ReleaseHead, guide.retailer_id)
        return WorkflowView(runs=[RunView.model_validate(r) for r in runs], releases=[ReleaseView.model_validate(r) for r in releases], active_release_id=head.release_id if head else None, connections=statuses())


@router.post('/guides/{guide_id}/analysis', response_model=RunView, status_code=201)
async def start_analysis(guide_id: UUID, body: StartAnalysis):
    async with sessions() as session:
        existing = await session.get(AnalysisRun, body.request_id)
        if existing:
            if existing.guide_id != guide_id:
                raise HTTPException(409, 'Request ID belongs to another guide.')
            return RunView.model_validate(existing)
        guide = await required(session, Guide, guide_id)
        if guide.status != 'ready':
            raise HTTPException(409, 'Resolve preparation failures before analyzing the guide.')
        count = guide.page_count
        if not count:
            raise HTTPException(409, 'No prepared pages.')
    model = body.model.strip()
    if body.provider != 'manual':
        config = connection(body.provider)
        model = model or config['model']
        if not config['key'] or not model:
            raise HTTPException(422, 'Add a provider API key and model in Connections first.')
    config = {'provider': body.provider, 'model': model, 'batch_pages': body.batch_pages, 'prompt_version': PROMPT_VERSION, 'schema_version': '1.0'}
    manual = body.provider == 'manual'
    payload = RunPayload(pending_batches=[] if manual else [list(range(i, min(i+body.batch_pages, count+1))) for i in range(1, count+1, body.batch_pages)],
        coverage=[PageCoverage(page=i, outcome='needs_review', note='Manual review required.') for i in range(1,count+1)] if manual else [],
        warnings=['Manual review: no AI analysis was performed. Review every page for coverage.'] if manual else []).model_dump(mode='json')
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cursor = await conn.execute('INSERT INTO analysis_runs(id,guide_id,status,version,config,payload) VALUES (%s,%s,%s,1,%s::jsonb,%s::jsonb) ON CONFLICT(id) DO NOTHING RETURNING id',
            (body.request_id, guide_id, 'complete' if manual else 'queued', json.dumps(config), json.dumps(payload)))
        inserted = await cursor.fetchone()
        if not inserted:
            cursor = await conn.execute('SELECT guide_id, config FROM analysis_runs WHERE id=%s', (body.request_id,))
            saved_guide, saved_config = await cursor.fetchone()
            if saved_guide != guide_id or saved_config != config:
                raise HTTPException(409, 'Request ID was already used for different analysis settings.')
        if inserted and not manual:
            await analyze_guide.configure(connection=conn, lock=f'analysis:{body.request_id}', queueing_lock=f'analysis:{body.request_id}').defer_async(run_id=str(body.request_id))
    async with sessions() as session:
        return RunView.model_validate(await required(session, AnalysisRun, body.request_id))


@router.post('/analysis/{run_id}/cancel')
async def cancel(run_id: UUID):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        if run.status not in {'queued', 'running', 'failed'}:
            raise HTTPException(409, 'This analysis is no longer running.')
        run.status = 'cancelled'
        run.version += 1
    return {'status': 'cancelled'}


@router.post('/analysis/{run_id}/retry')
async def retry(run_id: UUID):
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cursor = await conn.execute('SELECT status FROM analysis_runs WHERE id=%s FOR UPDATE', (run_id,))
        row = await cursor.fetchone()
        if not row or row[0] not in ('failed', 'cancelled'):
            raise HTTPException(409, 'Only failed or cancelled runs can be resumed.')
        await conn.execute("UPDATE analysis_runs SET status='queued',error=NULL,version=version+1 WHERE id=%s", (run_id,))
        await analyze_guide.configure(connection=conn, lock=f'analysis:{run_id}', queueing_lock=f'analysis:{run_id}').defer_async(run_id=str(run_id))
    return {'status': 'queued'}


@router.post('/analysis/{run_id}/rules', response_model=RunView)
async def add_rule(run_id: UUID, body: AddRule):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        guard(run, body.version)
        await check_evidence(session, run, body.spec)
        data = deepcopy(run.payload)
        data['rules'].append(Candidate(id=str(uuid4()), revision=1, status='pending', spec=body.spec, source_guide_id=str(run.guide_id)).model_dump(mode='json'))
        run.payload, run.version = data, run.version+1
        audit(session, run.id, body.actor, 'rule_added', data['rules'][-1])
        return RunView.model_validate(run)


@router.put('/analysis/{run_id}/rules/{rule_id}', response_model=RunView)
async def review_rule(run_id: UUID, rule_id: UUID, body: ReviewAction):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        guard(run, body.version)
        data = deepcopy(run.payload)
        rule = next((r for r in data['rules'] if r['id'] == str(rule_id)), None)
        if rule is None:
            raise HTTPException(404, 'Rule not found.')
        before = deepcopy(rule)
        if body.action == 'save':
            if not body.spec:
                raise HTTPException(422, 'Provide the edited rule.')
            if not body.note.strip():
                raise HTTPException(422, 'Explain the correction before saving.')
            await check_evidence(session, run, body.spec)
            rule.update(spec=body.spec.model_dump(mode='json'), status='pending', revision=rule['revision']+1, review=None, evidence_issues=[], carried_from_release_id=None, carried_from_rule_id=None)
        else:
            if (body.action == 'reject' or individual_review_reasons(RuleSpec.model_validate(rule['spec']), rule.get('evidence_issues', []), rule['spec']['title'].strip().casefold() in duplicate_titles(data['rules']))) and not body.note.strip():
                raise HTTPException(422, 'Add a note for rejections or rules requiring individual review.')
            if body.action == 'approve':
                if rule.get('evidence_issues'):
                    raise HTTPException(422, 'Resolve the source evidence issues by editing this proposal before approving it.')
                await check_evidence(session, run, RuleSpec.model_validate(rule['spec']))
            rule.update(carried_from_release_id=None, carried_from_rule_id=None, status='approved' if body.action == 'approve' else 'rejected', review={'actor': body.actor, 'note': body.note, 'revision': rule['revision'], 'at': datetime.now(timezone.utc).isoformat()})
        run.payload, run.version = data, run.version+1
        audit(session, run.id, body.actor, body.action, {'before': before, 'after': rule, 'note': body.note})
        return RunView.model_validate(run)


@router.post('/analysis/{run_id}/bulk-approve', response_model=RunView)
async def bulk_approve(run_id: UUID, body: BulkApproval):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        guard(run, body.version)
        data = deepcopy(run.payload)
        by_id = {r['id']: r for r in data['rules']}
        selected = []
        duplicates = duplicate_titles(data['rules'])
        # Validate the entire selection before changing any rule or audit history.
        for rule_id, revision in body.revisions.items():
            rule = by_id.get(str(rule_id))
            if rule is None:
                raise HTTPException(404, 'A selected rule does not belong to this draft.')
            if rule['revision'] != revision or rule['status'] != 'pending':
                raise HTTPException(409, 'A selected rule changed. Refresh and select the latest pending revisions.')
            spec = RuleSpec.model_validate(rule['spec'])
            if individual_review_reasons(spec, rule.get('evidence_issues', []), spec.title.strip().casefold() in duplicates):
                raise HTTPException(422, 'This selection includes rules requiring individual review.')
            await check_evidence(session, run, spec)
            selected.append(rule)
        timestamp = datetime.now(timezone.utc).isoformat()
        batch_id = str(uuid4())
        for rule in selected:
            before = deepcopy(rule)
            rule.update(status='approved', review={'actor': body.actor, 'note': body.note.strip(),
                        'revision': rule['revision'], 'at': timestamp, 'mode': 'bulk', 'batch_id': batch_id})
            audit(session, run.id, body.actor, 'approve', {'before': before, 'after': rule, 'batch_id': batch_id})
        run.payload, run.version = data, run.version + 1
        return RunView.model_validate(run)


async def active_baseline(session, run, lock=False):
    guide = await required(session, Guide, run.guide_id)
    head = await required(session, ReleaseHead, guide.retailer_id, lock)
    if not head.release_id:
        return None
    base = await session.scalar(select(RuleRelease).where(
        RuleRelease.id == head.release_id, RuleRelease.retailer_id == guide.retailer_id))
    if base is None:
        raise HTTPException(409, 'The active release is unavailable for this retailer.')
    return base


@router.get('/analysis/{run_id}/comparison', response_model=ComparisonView)
async def comparison(run_id: UUID):
    async with sessions() as session:
        run = await required(session, AnalysisRun, run_id)
        base = await active_baseline(session, run)
        return ComparisonView(base_release_id=base.id if base else None, base_name=base.name if base else '',
                              base_scope=base.payload['scope'] if base else '',
                              **compare_rules(run.payload['rules'], base.payload['rules'] if base else []))


@router.post('/analysis/{run_id}/carry-approvals', response_model=RunView)
async def carry_approvals(run_id: UUID, body: CarryApprovals):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        guard(run, body.version)
        base = await active_baseline(session, run, True)
        if not base or base.id != body.base_release_id:
            raise HTTPException(409, 'The active release changed or belongs to another retailer. Refresh the comparison.')
        if not body.scope_confirmed:
            raise HTTPException(422, 'Confirm this guide has the same operational scope as the baseline.')
        matches = compare_rules(run.payload['rules'], base.payload['rules'])['unchanged']
        previous = {r['stable_id']: r for r in base.payload['rules']}
        data = deepcopy(run.payload)
        selected = [r for r in data['rules'] if r['id'] in matches and r['status'] == 'pending']
        if not selected:
            raise HTTPException(409, 'No pending exact matches to carry forward.')
        for rule in selected:
            await check_evidence(session, run, RuleSpec.model_validate(rule['spec']))
        for rule in selected:
            before = deepcopy(rule)
            stable_id = matches[rule['id']]
            rule.update(status='approved', carried_from_release_id=str(base.id), carried_from_rule_id=stable_id,
                        review={'actor': body.actor, 'note': body.note.strip(), 'revision': rule['revision'],
                                'at': datetime.now(timezone.utc).isoformat(), 'mode': 'carried_forward',
                                'prior_review': deepcopy(previous[stable_id]['review'])})
            audit(session, run.id, body.actor, 'approval_carried_forward', {'before': before, 'after': rule})
        run.payload, run.version = data, run.version + 1
        return RunView.model_validate(run)


@router.put('/analysis/{run_id}/coverage', response_model=RunView)
async def review_coverage(run_id: UUID, body: CoverageAction):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        guard(run, body.version)
        if not body.note.strip():
            raise HTTPException(422, 'Explain the page coverage decision.')
        data = deepcopy(run.payload)
        page = next((p for p in data['coverage'] if p['page'] == body.page), None)
        if not page:
            raise HTTPException(404, 'Page coverage not found.')
        page.update(outcome=body.outcome, note=body.note)
        run.payload, run.version = data, run.version+1
        audit(session, run.id, body.actor, 'coverage_reviewed', body.model_dump())
        return RunView.model_validate(run)


def assemble_release(run, base, body):
    rules = run.payload['rules']
    if any(r['status'] == 'pending' for r in rules):
        raise HTTPException(409, 'Review every candidate before publishing.')
    approved = {r['id']: r for r in rules if r['status'] == 'approved'}
    if any(r.get('evidence_issues') for r in approved.values()):
        raise HTTPException(409, 'Approved rules cannot contain unresolved source evidence issues.')
    if any(p['outcome'] == 'needs_review' for p in run.payload['coverage']) or run.payload['pending_batches']:
        raise HTTPException(409, 'Resolve all page coverage before publishing.')
    old = base.payload['rules'] if base else []
    matches = compare_rules(rules, old)['unchanged']
    decisions = dict(body.decisions)
    for rid, rule in approved.items():
        if rule.get('carried_from_release_id'):
            if not base or rule['carried_from_release_id'] != str(base.id) or matches.get(rid) != rule.get('carried_from_rule_id'):
                raise HTTPException(409, 'Carried approvals no longer match the active baseline. Review those rules again.')
            stable_id = rule['carried_from_rule_id']
            if stable_id in decisions and decisions[stable_id] != 'replace:' + rid:
                raise HTTPException(422, 'A carried rule cannot also be retained or retired. Review it individually first.')
            decisions[stable_id] = 'replace:' + rid
    if set(decisions) != {r['stable_id'] for r in old}:
        raise HTTPException(422, 'Explicitly retain, replace or retire every rule in the previous release.')
    result, used = [], set()
    for previous in old:
        decision = decisions[previous['stable_id']]
        if decision == 'retain':
            result.append(deepcopy(previous))
        elif decision == 'retire':
            continue
        elif decision.startswith('replace:'):
            rid = decision.split(':',1)[1]
            if rid not in approved or rid in used:
                raise HTTPException(422, 'Each replacement must be a distinct approved proposal.')
            used.add(rid)
            r = approved[rid]
            result.append(dict(stable_id=previous['stable_id'], spec=r['spec'], source_guide_id=r['source_guide_id'], draft_id=rid, review=r['review']))
        else:
            raise HTTPException(422, 'Invalid change decision.')
    for rid, r in approved.items():
        if rid not in used:
            result.append(dict(stable_id=rid, spec=r['spec'], source_guide_id=r['source_guide_id'], draft_id=rid, review=r['review']))
    body.decisions = decisions
    return result


@router.post('/analysis/{run_id}/impact')
async def impact(run_id: UUID, body: PublishAction):
    async with sessions() as session:
        run = await required(session, AnalysisRun, run_id)
        guard(run, body.version)
        guide = await required(session, Guide, run.guide_id)
        base = await required(session, RuleRelease, body.base_release_id) if body.base_release_id else None
        if base and base.retailer_id != guide.retailer_id:
            raise HTTPException(422, 'Baseline must belong to the same retailer.')
        rules = assemble_release(run, base, body)
        scenarios = (await session.scalars(select(Scenario).where(Scenario.retailer_id == guide.retailer_id))).all()
        return {'scenarios': [{'id': str(s.id), 'name': s.name, 'before': evaluate_release(base.payload['rules'], s.payload['normalized']) if base else None, 'after': evaluate_release(rules, s.payload['normalized'])} for s in scenarios]}


@router.post('/analysis/{run_id}/publish', response_model=ReleaseView)
async def publish(run_id: UUID, body: PublishAction):
    async with sessions.begin() as session:
        run = await required(session, AnalysisRun, run_id, True)
        # A repeated publication request recovers the immutable release.
        previous = await session.scalar(select(RuleRelease).where(RuleRelease.run_id == run_id))
        if previous:
            return ReleaseView.model_validate(previous)
        guard(run, body.version)
        guide = await required(session, Guide, run.guide_id)
        head = await required(session, ReleaseHead, guide.retailer_id, True)
        if head.release_id != body.base_release_id:
            raise HTTPException(409, 'The active release changed. Compare against the current release before publishing.')
        if not body.coverage_confirmed or not body.impact_confirmed or not body.note.strip() or not body.scope.strip() or not body.name.strip() or not body.actor.strip():
            raise HTTPException(422, 'Confirm source coverage and scenario impact, and record publication notes.')
        if len(run.payload['coverage']) != guide.page_count or {p['page'] for p in run.payload['coverage']} != set(range(1,guide.page_count+1)):
            raise HTTPException(409, 'Full guide coverage has not been established.')
        base = await required(session, RuleRelease, body.base_release_id) if body.base_release_id else None
        rules = assemble_release(run, base, body)
        payload = ReleasePayload(rules=rules, base_release_id=str(body.base_release_id) if body.base_release_id else None, decisions=body.decisions, scope=body.scope, coverage_note=body.note, actor=body.actor, run_version=run.version)
        release = RuleRelease(id=uuid4(), retailer_id=guide.retailer_id, run_id=run_id, name=body.name.strip(), effective_date=body.effective_date, payload=payload.model_dump(mode='json'))
        session.add(release)
        await session.flush()
        head.release_id = release.id
        run.status, run.version = 'published', run.version+1
        audit(session, release.id, body.actor, 'published', payload.model_dump(mode='json'))
        return ReleaseView.model_validate(release)


@router.post('/releases/{release_id}/activate', response_model=ReleaseView)
async def activate_release(release_id: UUID, body: RestoreAction):
    async with sessions.begin() as session:
        release = await required(session, RuleRelease, release_id)
        head = await required(session, ReleaseHead, release.retailer_id, True)
        if head.release_id != body.expected_active_id:
            raise HTTPException(409, 'Active release changed. Refresh before restoring.')
        head.release_id = release_id
        audit(session, release.id, body.actor, 'activated', body.model_dump(mode='json'))
        return ReleaseView.model_validate(release)


@router.get('/releases/{release_id}/export')
async def export_release(release_id: UUID, format: Literal['json','markdown'] = 'json'):
    async with sessions() as session:
        release = await required(session, RuleRelease, release_id)
        value = ReleaseView.model_validate(release)
    if format == 'json':
        return Response(value.model_dump_json(indent=2), media_type='application/json', headers={'Content-Disposition': f'attachment; filename="rules-{release_id}.json"'})
    lines = [f'# {value.name}', f'Effective: {value.effective_date}', f'Scope: {value.payload.scope}', '']
    for r in value.payload.rules:
        lines += [f'## {r.spec.title}', r.spec.instruction, f'Obligation: {r.spec.obligation}; verification: {r.spec.verification}', f'Applies: {r.spec.applicability_text}']
        lines += [f'Exception: {e.description}' for e in r.spec.exceptions]
        lines += [f'Source: guide {r.source_guide_id}, PDF page {e.page}: {e.quote}' for e in r.spec.evidence]
        lines += ['']
    return Response('\n\n'.join(lines), media_type='text/markdown', headers={'Content-Disposition': f'attachment; filename="instructions-{release_id}.md"'})


@router.get('/audit/{entity_id}')
async def audit_history(entity_id: UUID):
    async with sessions() as session:
        records = (await session.scalars(select(AuditEvent).where(AuditEvent.entity_id == entity_id).order_by(AuditEvent.created_at))).all()
        return [{'actor': r.actor, 'action': r.action, 'at': r.created_at, 'payload': r.payload} for r in records]


@router.post('/shiphero/order', response_model=ScenarioView)
async def import_order(body: ShipHeroRequest):
    async with sessions() as session:
        await required(session, ReleaseHead, body.retailer_id)
    try:
        raw = await fetch_order(body.order_id)
        normalized, warnings = normalize(raw)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None
    async with sessions.begin() as session:
        order = raw['data']['wholesale_order']['data']
        scenario = Scenario(id=uuid4(), retailer_id=body.retailer_id, name=f'ShipHero {body.order_id}', payload={
            'raw': raw, 'normalized': normalized, 'overrides': {}, 'warnings': warnings,
            'mapping_version': MAPPING_VERSION, 'source': 'shiphero', 'account_id': (order.get('order') or {}).get('account_id'),
            'captured_at': datetime.now(timezone.utc).isoformat()})
        session.add(scenario)
        await session.flush()
        return ScenarioView.model_validate(scenario)


@router.get('/scenarios', response_model=list[ScenarioView])
async def list_scenarios(retailer_id: str):
    async with sessions() as session:
        return [ScenarioView.model_validate(s) for s in (await session.scalars(select(Scenario).where(Scenario.retailer_id == retailer_id).order_by(Scenario.created_at.desc()))).all()]


@router.post('/scenarios', response_model=ScenarioView)
async def create_scenario(body: ScenarioCreate):
    try:
        normalized, warnings = normalize(body.raw, body.overrides)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    async with sessions.begin() as session:
        await required(session, ReleaseHead, body.retailer_id)
        scenario = Scenario(id=uuid4(), retailer_id=body.retailer_id, name=body.name, payload={'raw': body.raw, 'normalized': normalized, 'overrides': body.overrides, 'warnings': warnings, 'mapping_version': MAPPING_VERSION, 'source': 'pasted_json', 'captured_at': datetime.now(timezone.utc).isoformat()})
        session.add(scenario)
        await session.flush()
        return ScenarioView.model_validate(scenario)


@router.post('/scenarios/{scenario_id}/evaluate/{release_id}', response_model=EvaluationView)
async def evaluate(scenario_id: UUID, release_id: UUID):
    async with sessions.begin() as session:
        scenario = await required(session, Scenario, scenario_id)
        release = await required(session, RuleRelease, release_id)
        if scenario.retailer_id != release.retailer_id:
            raise HTTPException(422, 'Scenario and release must belong to the same retailer.')
        result = evaluate_release(release.payload['rules'], scenario.payload['normalized'])
        result.update(mapping_version=scenario.payload['mapping_version'], effective_date=str(release.effective_date), scope=release.payload['scope'])
        evaluation = Evaluation(id=uuid4(), scenario_id=scenario_id, release_id=release_id, payload=result)
        session.add(evaluation)
        await session.flush()
        return EvaluationView(id=evaluation.id, scenario_id=scenario_id, release_id=release_id, created_at=evaluation.created_at, **{k:result[k] for k in ('evaluator_version','items','counts')})


@router.get('/scenarios/{scenario_id}/evaluations', response_model=list[EvaluationView])
async def evaluation_history(scenario_id: UUID):
    async with sessions() as session:
        records = (await session.scalars(select(Evaluation).where(Evaluation.scenario_id == scenario_id).order_by(Evaluation.created_at.desc()))).all()
        return [EvaluationView(id=r.id, scenario_id=r.scenario_id, release_id=r.release_id, created_at=r.created_at, **{k:r.payload[k] for k in ('evaluator_version','items','counts')}) for r in records]
