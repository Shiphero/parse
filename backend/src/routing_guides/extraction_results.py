"""Validate retained provider responses without discarding completed extraction work."""
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from pydantic import ValidationError
from routing_guides.rules import Extraction


def validation_messages(exc: ValidationError) -> list[str]:
    # Exclude raw inputs and validator context (which can contain source values).
    return [f'{".".join(str(p) for p in e["loc"]) or "rule"}: {e["msg"]}'
            for e in exc.errors(include_input=False, include_context=False, include_url=False)]


def parse_extraction(raw: Any) -> Extraction:
    extraction = Extraction.model_validate(raw)
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
