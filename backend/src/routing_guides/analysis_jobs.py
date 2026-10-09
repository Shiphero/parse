"""Resumable full-page extraction. Completed batches and decisions survive retries."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import select
from routing_guides.analysis_provider import analyze, ProviderFailure
from routing_guides.db import sessions
from routing_guides.models import AnalysisRun, GuidePage
from routing_guides.storage import guide_directory


def validate_evidence(spec, pages: dict[int, str | None]):
    for evidence in spec.evidence:
        if evidence.page not in pages:
            raise ValueError('Evidence refers to a page outside the guide.')
        if evidence.kind == 'text':
            compact = lambda value: ' '.join((value or '').split()).casefold()
            if compact(evidence.quote) not in compact(pages[evidence.page]):
                raise ValueError(f'Text evidence on page {evidence.page} does not match the extracted source. Use visual evidence only if verified in the image.')


def reconcile_warnings(rules: list[dict]) -> list[str]:
    titles = {}
    for rule in rules:
        titles.setdefault(rule['spec']['title'].strip().casefold(), []).append(rule['id'])
    return [f'Possible duplicate or conflict: {title}. Review these proposals together; no automatic merge was made.' for title, ids in titles.items() if len(ids) > 1]


async def run_analysis(run_id: UUID):
    async with sessions.begin() as session:
        run = await session.get(AnalysisRun, run_id, with_for_update=True)
        if not run or run.status in {'cancelled', 'complete', 'published'}:
            return
        run.status, run.error = 'running', None
        config, guide_id = deepcopy(run.config), run.guide_id
    try:
        async with sessions() as session:
            source = (await session.scalars(select(GuidePage).where(GuidePage.guide_id == guide_id).order_by(GuidePage.page_index))).all()
            pages = {p.page_index+1: p.text for p in source}
        context = '\n\n'.join(f'PDF page {number}:\n{text or "[Image-only page]"}' for number, text in pages.items())
        while True:
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                if run.status == 'cancelled':
                    return
                payload = deepcopy(run.payload)
                pending = payload['pending_batches']
                if not pending:
                    payload['warnings'] = list(dict.fromkeys(payload['warnings'] + reconcile_warnings(payload['rules'])))
                    run.payload, run.status = payload, 'complete'
                    run.version += 1
                    return
                batch = pending[0]
            requested = [{'page': number, 'text': pages[number]} for number in batch]
            try:
                for attempt in range(3):
                    try:
                        output = await analyze(config['provider'], config['model'], requested, context, guide_directory(guide_id))
                        break
                    except ProviderFailure as exc:
                        if not exc.retryable or attempt == 2:
                            raise
                        await asyncio.sleep(2 ** (attempt+1))
                extraction = output.extraction
                numbers = [p.page for p in extraction.coverage]
                if sorted(numbers) != sorted(batch):
                    raise ProviderFailure('Model coverage did not match every requested page. Retry this batch.')
                for rule in extraction.rules:
                    validate_evidence(rule, pages)
                    if not any(e.page in batch for e in rule.evidence):
                        raise ProviderFailure('A proposed rule had no evidence on its target pages.')
            except ProviderFailure as exc:
                if exc.split and len(batch) > 1:
                    async with sessions.begin() as session:
                        run = await session.get(AnalysisRun, run_id, with_for_update=True)
                        if run.status == 'cancelled':
                            return
                        data = deepcopy(run.payload)
                        midpoint = len(batch)//2
                        data['pending_batches'] = [batch[:midpoint], batch[midpoint:]] + data['pending_batches'][1:]
                        run.payload = data
                    continue
                raise
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                if run.status == 'cancelled':
                    return
                data = deepcopy(run.payload)
                # Queue execution lock serializes this run; batch result and checkpoint commit together.
                data['pending_batches'] = data['pending_batches'][1:]
                data['coverage'] += [p.model_dump() for p in extraction.coverage]
                data['warnings'] += extraction.warnings
                data['batches'].append({'pages': batch, 'model': output.model, 'usage': output.usage, 'completed_at': datetime.now(timezone.utc).isoformat()})
                data['rules'] += [{'id': str(uuid4()), 'revision': 1, 'status': 'pending', 'spec': rule.model_dump(mode='json'), 'source_guide_id': str(guide_id), 'review': None} for rule in extraction.rules]
                run.payload = data
                run.version += 1
    except Exception as exc:
        async with sessions.begin() as session:
            run = await session.get(AnalysisRun, run_id, with_for_update=True)
            if run.status != 'cancelled':
                run.status = 'failed'
                run.error = str(exc) if isinstance(exc, (ProviderFailure, ValueError)) else 'Analysis stopped unexpectedly. Completed batches are saved; retry to resume.'
