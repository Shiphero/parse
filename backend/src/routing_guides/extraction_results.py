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
    try:
        extraction = Extraction.model_validate(raw)
    except ValidationError as exc:
        # Only downgrade a known semantic mismatch in provider proposals. The
        # editor/API still use strict RuleSpec validation, and all other errors
        # must pass full validation below. Never infer a check or change evidence.
        indexes = {e['loc'][1] for e in exc.errors(include_input=False, include_context=False)
                   if e['type'] == 'unmapped_catalog_rule' and len(e['loc']) == 2
                   and e['loc'][0] == 'rules' and isinstance(e['loc'][1], int)}
        if not indexes or not isinstance(raw, dict):
            raise
        normalized = deepcopy(raw)
        for index in sorted(indexes):
            proposal = normalized['rules'][index]
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
