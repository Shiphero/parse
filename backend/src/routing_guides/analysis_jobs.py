"""Resumable full-page extraction. Completed batches and decisions survive retries."""
import asyncio
import re
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import select
from routing_guides.analysis_provider import analyze, ProviderFailure
from routing_guides.db import sessions
from routing_guides.models import AnalysisRun, GuidePage
from routing_guides.storage import guide_directory


def normalized_excerpt(value: str | None) -> str:
    """Normalize typography only, preserving words, numbers and meaningful punctuation."""
    value = unicodedata.normalize('NFKC', value or '').translate(str.maketrans({'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u00ad': ''}))
    value = re.sub(r'-[ \t]*\r?\n[ \t]*(?=\w)', '-', value)
    return ' '.join(value.split()).casefold()


def evidence_issues(spec, pages: dict[int, str | None]) -> list[str]:
    issues = []
    for evidence in spec.evidence:
        if evidence.page not in pages:
            issues.append(f'Evidence refers to PDF page {evidence.page}, outside this guide.')
        elif evidence.kind == 'text':
            quote = normalized_excerpt(evidence.quote)
            if not quote or quote not in normalized_excerpt(pages[evidence.page]):
                issues.append(f'Text evidence on PDF page {evidence.page} does not match the extracted source. Correct the excerpt or page, verify visual evidence against the image, or reject this proposal.')
    return issues


def validate_evidence(spec, pages: dict[int, str | None]):
    issues = evidence_issues(spec, pages)
    if issues:
        raise ValueError(' '.join(issues))


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
                        directory = guide_directory(guide_id)
                        response_path = directory / 'analysis' / str(run_id) / ('batch-' + '-'.join(map(str, batch)) + '.json')
                        output = await analyze(config['provider'], config['model'], requested, context, directory, response_path=response_path)
                        break
                    except ProviderFailure as exc:
                        if not exc.retryable or attempt == 2:
                            raise
                        await asyncio.sleep(2 ** (attempt+1))
                extraction = output.extraction
                numbers = [p.page for p in extraction.coverage]
                if sorted(numbers) != sorted(batch):
                    raise ProviderFailure('Model coverage did not match every requested page. Retry this batch.')
                candidates = []
                for rule in extraction.rules:
                    issues = evidence_issues(rule, pages)
                    if not any(e.page in batch for e in rule.evidence):
                        issues.append('This proposal has no evidence on its requested pages. Verify its source before approval.')
                    candidates.append({'id': str(uuid4()), 'revision': 1, 'status': 'pending', 'spec': rule.model_dump(mode='json'), 'source_guide_id': str(guide_id), 'review': None, 'evidence_issues': issues})
                    if issues:
                        affected = {e.page for e in rule.evidence if e.page in batch} or set(batch)
                        for coverage in extraction.coverage:
                            if coverage.page in affected:
                                coverage.outcome = 'needs_review'
                                coverage.note += ' A proposal has unverified source evidence; review its citation before resolving coverage.'
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
                data['batches'].append({'pages': batch, 'model': output.model, 'usage': output.usage, 'completed_at': datetime.now(timezone.utc).isoformat(), 'prompt_version': output.prompt_version, 'evidence_review_required': sum(bool(r['evidence_issues']) for r in candidates)})
                data['rules'] += candidates
                run.payload = data
                run.version += 1
    except Exception as exc:
        async with sessions.begin() as session:
            run = await session.get(AnalysisRun, run_id, with_for_update=True)
            if run.status != 'cancelled':
                run.status = 'failed'
                run.error = str(exc) if isinstance(exc, (ProviderFailure, ValueError)) else 'Analysis stopped unexpectedly. Completed batches are saved; retry to resume.'
