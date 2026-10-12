"""Three-valued evaluation with exact arithmetic; never executes model-generated code."""
from decimal import Decimal, InvalidOperation
from typing import Any
from routing_guides.rules import Expression, RuleSpec

VERSION = '1.1'
MISSING = object()
UNITS = {'oz': ('mass', Decimal('28.349523125')), 'lb': ('mass', Decimal('453.59237')),
         'g': ('mass', Decimal(1)), 'kg': ('mass', Decimal(1000)),
         'in': ('length', Decimal('25.4')), 'cm': ('length', Decimal(10)), 'mm': ('length', Decimal(1))}


def resolve(data, path):
    parts = path.split('.')
    def walk(obj, rest):
        if not rest:
            return obj if obj is not None else MISSING
        key, *tail = rest
        if key == '*':
            if not isinstance(obj, list):
                return MISSING
            vals = [walk(item, tail) for item in obj]
            if any(v is MISSING for v in vals):
                return MISSING
            return [sub for val in vals for sub in (val if isinstance(val, list) else [val])]
        if not isinstance(obj, dict) or key not in obj:
            return MISSING
        return walk(obj[key], tail)
    return walk(data, parts)


def number(value, unit=None):
    if isinstance(value, dict):
        source = value.get('unit')
        if source not in UNITS or unit not in UNITS or UNITS[source][0] != UNITS[unit][0]:
            raise ValueError('A compatible measurement unit is required.')
        return number(value.get('value')) * UNITS[source][1] / UNITS[unit][1]
    if unit is not None:
        raise ValueError('Measurement is missing its unit.')
    if isinstance(value, bool) or value is None:
        raise ValueError('Expected a number.')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Expected a number.') from None
    if not result.is_finite():
        raise ValueError('Expected a finite number.')
    return result


def compare(actual, expected, op, unit=None):
    if actual is MISSING:
        return None
    if op == 'in':
        values = [compare(actual, e, 'eq', unit) for e in expected]
        return True if True in values else None if None in values else False
    if unit or op in {'lt', 'lte', 'gt', 'gte'} or isinstance(expected, (int, float)) and not isinstance(expected, bool):
        left, right = number(actual, unit), number(expected)
    else:
        if type(actual) is not type(expected):
            return None
        left, right = actual, expected
    return {'eq': lambda: left == right, 'ne': lambda: left != right, 'lt': lambda: left < right,
            'lte': lambda: left <= right, 'gt': lambda: left > right, 'gte': lambda: left >= right}[op]()


def expression(expr: Expression, facts: dict) -> tuple[bool | None, str]:
    try:
        if expr.op in {'all', 'any', 'not'}:
            results = [expression(child, facts)[0] for child in expr.children]
            if expr.op == 'not':
                result = None if results[0] is None else not results[0]
            elif expr.op == 'all':
                result = False if False in results else None if None in results else True
            else:
                result = True if True in results else None if None in results else False
            return result, f'{expr.op}: {results}'
        actual = resolve(facts, expr.path)
        if expr.op == 'exists':
            # An absent field means unknown, not proof that the physical thing is absent.
            return (None if actual is MISSING else bool(actual)), f'{expr.path}: presence check'
        if actual is MISSING:
            return None, f'Missing {expr.path}'
        if expr.op in {'count', 'sum', 'unique_count'}:
            if not isinstance(actual, list):
                return None, f'{expr.path} must be an explicit complete array'
            if expr.op == 'count':
                actual = len(actual)
            elif expr.op == 'unique_count':
                if any(not isinstance(v, (str, int, float, bool)) for v in actual):
                    return None, 'Unique count requires scalar values'
                actual = len({(type(v), v) for v in actual})
            else:
                actual = sum((number(v, expr.unit) for v in actual), Decimal(0))
            result = compare(actual, expr.value, expr.comparator)
        else:
            result = compare(actual, expr.value, expr.op, expr.unit)
        return result, f'{expr.path}: {actual!s}; expected {expr.comparator or expr.op} {expr.value!s} {expr.unit or ""}'.strip()
    except (ValueError, TypeError, KeyError, InvalidOperation):
        return None, f'Cannot compare {expr.path}: check data types and units'


def evaluate_rule(rule_id: str, rule: RuleSpec, snapshot: dict) -> dict[str, Any]:
    base = dict(rule_id=rule_id, title=rule.title, instruction=rule.instruction, obligation=rule.obligation)
    if rule.purpose == 'general_guidance':
        return dict(base, outcome='not_applicable', reason='General guidance is not a shipment validation rule.', subjects=[])
    if rule.purpose == 'unclassified':
        return dict(base, outcome='cannot_determine', reason='Rule use has not been classified; no shipment check was executed.', subjects=[])
    if rule.subject in {'order', 'shipment', 'document', 'label'}:
        targets = [snapshot.get('shipment', {})]
    else:
        targets = snapshot.get({'carton': 'cartons', 'pallet': 'pallets', 'item': 'items'}[rule.subject])
    if not isinstance(targets, list) or not targets:
        return dict(base, outcome='cannot_determine', reason='No complete subject data supplied.', subjects=[])
    results = []
    for i, target in enumerate(targets):
        facts = {**target, 'shipment': snapshot.get('shipment', {}), 'evidence': snapshot.get('evidence', {})}
        applicability, why = expression(rule.applicability, facts) if rule.applicability else (True, '')
        outcome = 'cannot_determine'
        if applicability is False:
            outcome, why = 'not_applicable', 'Applicability condition is false.'
        elif applicability is None:
            why = 'Applicability unknown: ' + why
        else:
            exception_results = [expression(e.condition, facts)[0] if e.condition else None for e in rule.exceptions]
            if True in exception_results:
                outcome, why = 'not_applicable', 'An approved exception applies.'
            elif None in exception_results:
                why = 'An exception cannot be determined from the supplied facts.'
            elif rule.unresolved_questions:
                why = 'Unresolved: ' + '; '.join(rule.unresolved_questions)
            elif rule.verification != 'data' or rule.assertion is None:
                why = 'Requires human inspection or external evidence; no automated pass is inferred.'
            else:
                result, why = expression(rule.assertion, facts)
                outcome = 'pass' if result is True else 'fail' if result is False else 'cannot_determine'
        results.append({'subject': str(target.get('id', i+1)), 'outcome': outcome, 'reason': why})
    outcomes = {r['outcome'] for r in results}
    overall = next((s for s in ('fail', 'cannot_determine', 'pass') if s in outcomes), 'not_applicable')
    return dict(base, outcome=overall, reason=f'{len(results)} subject(s) checked.', subjects=results)


def evaluate_release(rules: list[dict], snapshot: dict) -> dict:
    parsed = [(r['stable_id'], RuleSpec.model_validate(r['spec'])) for r in rules]
    items = [evaluate_rule(rid, spec, snapshot) for rid, spec in parsed if spec.purpose != 'general_guidance']
    return {'evaluator_version': VERSION, 'items': items, 'guidance_count': sum(spec.purpose == 'general_guidance' for _, spec in parsed),
            'counts': {s: sum(i['outcome'] == s for i in items) for s in ('pass', 'fail', 'cannot_determine', 'not_applicable')}}
