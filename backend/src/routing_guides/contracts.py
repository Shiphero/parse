"""Initial domain contracts. These are drafts, not a completed validation engine."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Contract):
    document_version_id: UUID
    page_index: int = Field(ge=0, description="Zero-based PDF page index")
    printed_page: str | None = None
    excerpt: str | None = None
    image_asset_id: UUID | None = None


class RuleCandidate(Contract):
    schema_version: Literal["0.1"] = "0.1"
    retailer_id: str
    title: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    obligation: Literal["required", "prohibited", "recommended", "informational"]
    subject: Literal["order", "shipment", "pallet", "carton", "item", "label", "document"]
    applicability_text: str
    exceptions: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)
    verification: Literal["data", "human", "external_evidence", "unresolved"]
    unresolved_questions: list[str] = Field(default_factory=list)
    # Executable expressions are deliberately deferred until operator semantics are reviewed.


class ScenarioSnapshot(Contract):
    schema_version: Literal["0.1"] = "0.1"
    source: Literal["pasted_json", "shiphero", "synthetic"]
    captured_at: datetime
    raw_payload: dict[str, Any]
    # Preserve wholesale packing_layout in raw_payload without flattening containers.
    overrides: dict[str, Any] = Field(default_factory=dict)
    supplemental_evidence: dict[str, Any] = Field(default_factory=dict)


class EvaluationOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    CANNOT_DETERMINE = "cannot_determine"
    NOT_APPLICABLE = "not_applicable"


class AnalysisRequest(Contract):
    run_id: UUID
    provider: str
    model: str
    document_asset_ids: list[UUID] = Field(min_length=1)
    prompt_version: str
    schema_version: str
    requires_vision: bool = True


class AnalysisResult(Contract):
    run_id: UUID
    provider: str
    requested_model: str
    returned_model: str | None
    status: Literal["complete", "incomplete", "failed"]
    candidates: list[RuleCandidate]
    warnings: list[str] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)


class AnalysisProvider(Protocol):
    """Native SDK adapters implement this contract in the analysis milestone."""

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult: ...
