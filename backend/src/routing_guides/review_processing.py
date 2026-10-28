"""Bounded provider work; database checkpoints stay serial and cancellation drains tasks."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json

REVIEW_CONCURRENCY = 4


def now():
    return datetime.now(timezone.utc).isoformat()


def preparation_fingerprint(candidate):
    # Preparation uses this rule and immutable source pages, never peer decisions.
    from routing_guides.assessment import assessment_fingerprint
    return assessment_fingerprint(candidate, [])


def resolution_context(candidate):
    record = candidate.get('resolution') or {}
    value = {k: record.get(k) for k in ('revision', 'changes', 'questions', 'capability_gaps', 'failed')}
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def reusable_preparation(candidate, job):
    record = candidate.get('resolution') or {}
    if (record.get('failed') or record.get('revision') != candidate['revision']
            or record.get('provider') != job['resolution_provider'] or record.get('model') != job['resolution_model']):
        return False
    if record.get('output_fingerprint'):
        return (record['output_fingerprint'] == preparation_fingerprint(candidate)
                and record.get('verifier_model') == job['model']
                and (record.get('prompt_version') == job['resolution_version'] or
                     job['resolution_version'] == 'rule-resolution-1.2' and record.get('prompt_version') == 'rule-resolution-1.1'))
    # Successful pre-upgrade no-change proposals did not call the verifier. Preserve
    # those results on untouched revisions; changed/proposed definitions are rechecked.
    return (job['resolution_version'] == 'rule-resolution-1.2'
            and record.get('prompt_version') == 'rule-resolution-1.1' and not record.get('changes')
            and not candidate.get('review') and not candidate.get('automation_hold'))


@asynccontextmanager
async def completed_batch(items, operation):
    async def perform(item):
        try:
            return item, await operation(item), None
        except Exception as error:
            return item, None, error

    tasks = [asyncio.create_task(perform(item)) for item in items]
    async def results():
        for task in asyncio.as_completed(tasks):
            yield await task
    try:
        yield results()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
