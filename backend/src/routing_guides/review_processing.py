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
    from routing_guides.classification_mapping import needs_auto_classification
    record = candidate.get('resolution') or {}
    if (record.get('failed') or record.get('revision') != candidate['revision']
            or record.get('provider') != job['resolution_provider'] or record.get('model') != job['resolution_model']):
        return False
    upgraded = (job['resolution_version'] == 'rule-resolution-1.4'
                and record.get('prompt_version') in {'rule-resolution-1.1', 'rule-resolution-1.2', 'rule-resolution-1.3'})
    if upgraded and needs_auto_classification(candidate['spec']):
        return False
    if record.get('output_fingerprint'):
        compatible = record.get('prompt_version') == job['resolution_version']
        if upgraded or (job['resolution_version'] == 'rule-resolution-1.3' and record.get('prompt_version') in {'rule-resolution-1.1', 'rule-resolution-1.2'}):
            # Old unapplied proposals were verified as a whole, not independently.
            compatible = all(change.get('applied') for change in record.get('changes', []))
        return (record['output_fingerprint'] == preparation_fingerprint(candidate)
                and record.get('verifier_model') == job['model']
                and (compatible or
                     job['resolution_version'] == 'rule-resolution-1.2' and record.get('prompt_version') == 'rule-resolution-1.1'))
    # Successful pre-upgrade no-change proposals did not call the verifier. Preserve
    # those results on untouched revisions; changed/proposed definitions are rechecked.
    return (job['resolution_version'] in {'rule-resolution-1.2', 'rule-resolution-1.3', 'rule-resolution-1.4'}
            and record.get('prompt_version') == 'rule-resolution-1.1' and not record.get('changes')
            and not candidate.get('review') and not candidate.get('automation_hold'))


@asynccontextmanager
async def completed_batch(items, operation, *, keep_running=lambda: True):
    """Refill a bounded pool after each checkpoint, without waiting for slow peers."""
    async def perform(item):
        try:
            return item, await operation(item), None
        except Exception as error:
            return item, None, error

    remaining = iter(items)
    tasks = set()
    failed = False
    def refill():
        while len(tasks) < REVIEW_CONCURRENCY and not failed and keep_running():
            try:
                item = next(remaining)
            except StopIteration:
                break
            tasks.add(asyncio.create_task(perform(item)))
    refill()
    async def results():
        nonlocal failed
        while tasks:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            failed = failed or any(task.result()[2] is not None for task in done)
            for task in done:
                tasks.remove(task)
                yield await task
                # The consumer persists the result and may stop scheduling after
                # a fatal failure. Already-running results are still drained.
                refill()
    try:
        yield results()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
