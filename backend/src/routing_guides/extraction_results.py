"""Validate retained provider responses without discarding completed extraction work."""
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from pydantic import ValidationError
from routing_guides.rules import Extraction


def validation_messages(exc: ValidationError) -> list[str]:
    # Exclude raw inputs and validator context (which can contain source values).
    return [f'{".".join(str(p) for p in e["loc"]) or "rule"}: {e["msg"]}'
            for e in exc.errors(include_input=False, include_context=False, include_url=False)]


def parse_extraction(raw: Any) -> Extraction:
    warnings = []
    normalized = raw
    # A known provider-only metadata alias belongs in the page note, never in
    # rule evidence. Keep malformed values and all unknown fields strict.
    if isinstance(raw, dict) and isinstance(raw.get('coverage'), list):
        for index, coverage in enumerate(raw['coverage']):
            if (isinstance(coverage, dict) and isinstance(coverage.get('quote_note'), str)
                    and isinstance(coverage.get('note'), str)):
                if normalized is raw:
                    normalized = deepcopy(raw)
                item = normalized['coverage'][index]
                quote_note = item.pop('quote_note')
                if quote_note.strip():
                    item['note'] = '\n'.join(part for part in (item['note'], quote_note) if part)
                warnings.append(f'Coverage item {index + 1}: provider quote_note normalized into note; original response retained.')
    try:
        extraction = Extraction.model_validate(normalized)
    except ValidationError as exc:
        # Only downgrade a known semantic mismatch in provider proposals. The
        # editor/API still use strict RuleSpec validation, and all other errors
        # must pass full validation below. Never infer a check or change evidence.
        errors = {e['loc'][1]: e['type'] for e in exc.errors(include_input=False, include_context=False)
                   if e['type'] in {'unmapped_catalog_rule', 'rule_type_subject_mismatch', 'rule_type_category_mismatch'} and len(e['loc']) == 2
                   and e['loc'][0] == 'rules' and isinstance(e['loc'][1], int)}
        if not errors or not isinstance(raw, dict):
            raise
        if normalized is raw:
            normalized = deepcopy(raw)
        for index in sorted(errors):
            proposal = normalized['rules'][index]
            if errors[index] in {'rule_type_subject_mismatch', 'rule_type_category_mismatch'}:
                # Recover instruction-only proposals, not conflicting executable
                # checks or malformed fields that happen to share this error.
                if proposal.get('standard_check') is not None or proposal.get('assertion') is not None:
                    continue
                dimension = 'subject' if errors[index] == 'rule_type_subject_mismatch' else 'operational_category'
                note = ('Needs rule type mapping: the provider proposed '
                        f'{proposal["rule_type"]["id"]} with {dimension} {proposal[dimension]}, '
                        'which conflicts with that rule type. The disputed rule type and workflow '
                        'assignments were removed; choose a compatible mapping before approval. '
                        'The original provider response is retained.')
                proposal.update(rule_type=None, placements=[], consumption_points=[], verification='unresolved')
                proposal.setdefault('unresolved_questions', []).append(note)
                warnings.append(f'Proposal {index + 1}: {note}')
                continue
            original_verification = proposal['verification']
            removed_assertion = proposal.get('assertion') is not None
            note = ('Needs verification mapping: the provider proposed '
                    f'{original_verification} verification without a standard check. '
                    'Choose a compatible catalog check or instruction-only rule type before approval.')
            if removed_assertion:
                note += ' The proposed custom assertion was removed from this draft; the original provider response is retained.'
            proposal.update(verification='unresolved', assertion=None)
            proposal.setdefault('unresolved_questions', []).append(note)
            warnings.append(f'Proposal {index + 1}: {note}')
        extraction = Extraction.model_validate(normalized)
    extraction.warnings.extend(warnings)
    if isinstance(raw, dict) and 'warnings' not in raw:
        extraction.warnings.append('Provider omitted the optional warnings list; no warning assessment was supplied.')
    return extraction


def save_response(path: Path, value: dict):
    """An accepted provider response survives local validation failures and restarts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.response-', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w') as destination:
            json.dump(value, destination, allow_nan=False)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
