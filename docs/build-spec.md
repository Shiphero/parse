# Routing guide parser: local build specification

Status: local workflow implemented, October 9, 2026. Live provider extraction and live ShipHero access require configured credentials and representative acceptance data. See [workflow.md](workflow.md) for usage, field semantics and precise limits.

## Objective and scope

Convert retailer guides into source-backed, reviewed rules that supply human instructions and deterministic shipment checks. Updated guides produce new drafts and explicit change decisions. Begin with Ulta, then challenge the contracts with Nordstrom, Walmart and Michaels. Local deployment is the current scope; shared deployment remains a separate milestone.

## Architecture

| Layer | Implementation |
| --- | --- |
| Interface | React, TypeScript, Vite; guide library, source viewer, analysis, review, releases, scenarios and connections |
| API | FastAPI/Pydantic; generated OpenAPI TypeScript types |
| Persistence | PostgreSQL 17, SQLAlchemy, Alembic; relational IDs plus versioned JSON rule manifests |
| Jobs | Procrastinate; PostgreSQL queue and separate worker |
| Assets | Immutable originals and rendered PNGs in a local Docker volume |
| AI | Native Anthropic Messages and OpenAI Responses SDK adapters; common validated extraction contract |
| Execution | Docker Compose; localhost ports 5180 and 8180; database has no host port |

No separate Redis or model orchestration framework is required. Dependency versions are locked. Queue schema migrations remain separate from application migrations. Non-secret models and upload limits live in PostgreSQL. Production credentials are injected by ECS/Secrets Manager; local development supports volume overrides saved atomically with mode 0600. Credentials never enter PostgreSQL or browser responses. Reviewer names are self-declared, not authenticated identity.

## Delivered workflow

1. **Upload and prepare.** Stream/save immutable PDF, hash/deduplicate per retailer, enqueue atomically with the record, render each page and extract available text. Every page gets a coverage record. Image-only pages are informational; real preparation failures need attention. No page truncation.
2. **Analyze.** User chooses provider/model. Each page batch includes its images plus the entire guide's extracted text for cross-references. Request/output size failures split batches; unsupported models and irreducible context failures stop visibly. Transient retries are bounded. Completed results and checkpoints commit together. Cancellation stops subsequent work; reruns produce fresh drafts.
3. **Validate proposals.** Pydantic validates the bounded rule language. All target pages must have coverage. Text citations must match a real source page after conservative typography/whitespace/case normalization. Mismatches are retained as flagged pending drafts, block approval and leave affected page coverage unresolved while subsequent batches continue. Visual evidence retains the page image and optional normalized region. Possible same-title duplicates are flagged, never automatically merged. Coverage and semantics still require human review.
4. **Review.** User sees instructions, scope, exceptions, verification and source images. Eligible rules can be selected and approved by type with an optional batch note; flagged rules require individual attention. Approval notes are optional, including for individually reviewed flagged rules; corrections and rejections require notes. Each edit increments its revision and clears approval. Every approval/rejection records actor, note, exact revision and time. Manual review uses the same controls without pretending an AI call occurred.
5. **Compare and publish.** Unique exact text matches can carry forward approval after scope confirmation and source revalidation. Their previous review history and stable identity are preserved; all other previous rules need an explicit retain/replace/retire choice. Replacements preserve stable IDs; additions have new IDs; retention preserves old evidence. Old/new source and field differences are visible. Publication requires all candidates resolved, all page coverage resolved, explicit effective date/scope/notes and scenario-impact acknowledgement. Row locks and version guards prevent stale publication. Releases are immutable; active-release restoration is audited.
6. **Use instructions.** Review releases in the UI or export their instruction text as Markdown and their structured rules as JSON.
7. **Run scenarios.** Paste canonical JSON or a ShipHero wholesale payload, save an immutable snapshot with explicit overrides, choose an exact release and evaluate in Python. Persist results against that snapshot/release/mapping/evaluator version. Preview saved-scenario impact before publishing a change.
8. **Read ShipHero.** Fetch one wholesale order by public API ID using an access token, record source/account/time and preserve nested packing structure. Only operational and postal destination fields are requested; unrelated contact/payment fields are excluded. No mutations, implicit refreshes or order data sent to AI.

## Data model

- `Guide`, `GuidePage`: original document version, page text/image statuses and preparation errors.
- `AnalysisRun`: provider/model/prompt/schema settings, lifecycle, version, batch checkpoints, coverage, usage, warnings and candidate revisions.
- `AuditEvent`: append-only application history of rule edits, coverage decisions, review and publication/restoration.
- `RuleRelease`: immutable approved rule manifest, stable identities, prior-release decisions, scope, effective date and actor.
- `ReleaseHead`: explicit active release per retailer; evaluations can select older releases.
- `Scenario`: raw source input, normalized facts, overrides, mapping version, warnings and capture provenance.
- `Evaluation`: pinned scenario/release plus per-rule and per-subject outcomes and reasons.

The original prototype contracts remain historical reference in `contracts.py`. Current executable contracts are in `rules.py`; `/api/contracts` exposes schema version 1.0. Runtime API documentation is at `/docs`.

## Core semantics

- Rule purpose separates general guidance from shipment validation independently of verification method. General guidance remains in instructions and exports but is excluded from shipment checks. Existing unclassified drafts can be classified by a resumable text-only AI job with per-rule reasons and revision checks; ongoing contact maintenance, onboarding and EDI setup are guidance, while per-shipment ASN timing and physical requirements remain shipment validation. Unclassified legacy rules require classification before approval and publication.
- Required, prohibited, recommended and informational obligations remain distinct.
- Data, human, external-evidence and unresolved verification remain distinct.
- Supported expressions: comparisons, allowed values, existence, all/any/not, counts, sums and unique counts. Compose ranges with all; evaluate consistency within each subject using unique counts.
- True means compliance. Missing information, incompatible types/units, unknown applicability, unresolved exceptions and inspection requirements do not pass.
- Empty/missing subject collections cannot imply blanket compliance. Not applicable requires a known-false applicability or a known-true exception.
- Exact Decimal arithmetic converts explicit mass/length units. ShipHero dimensions are inches and weight is ounces per its current documentation.
- Nested packing remains intact. Never sum parent/child weights, infer a whole physical load from one order, or assume carton PO membership from the order header. CasePack quantities are retained without inferring aggregate weight or each totals.
- A release effective date does not automatically choose a historical policy; the user selects the applicable release and scope.

## Verification

`make check` runs only at commit checkpoints. Tests cover arithmetic boundaries, unknown propagation, nesting, citations, stale review revisions, approval invalidation, immutable/repeated publication, pinned scenario results, failed/resumed extraction and incomplete coverage. Integration fixtures use rollback-only database transactions. SDK request/response checks use mocks and do not prove live access or extraction quality.

Repository changes are committed automatically at substantial milestones using the user's Git identity, without AI attribution. No remote exists and no push is authorized. External review remains opt-in.

## Remaining acceptance and deployment work

- Configure a provider key/model and run original Ulta PDF extraction; review resulting quality with the user. Compare providers against a curated source-backed gold set. No model quality or accuracy score is invented.
- Obtain an authentic same-scope older/newer guide pair for semantic extraction acceptance. Current comparison preserves explicit identity decisions but does not autonomously resolve splits, merges or contradictions.
- Verify read-only ShipHero import with a real wholesale ID and token. Confirm destination semantics for each retailer workflow.
- Dedicated OCR, non-PDF Word/Excel ingestion and trained classifiers are not implemented; vision models receive image-only PDF pages.
- The ECS POC uses one service with API/UI and worker containers from one image, PostgreSQL, and shared EFS. GitHub Actions handles checks, image publication, migrations and application deployment; Terraform owns infrastructure. See `docs/ecs-deployment.md`. Internal access/SSO, backups, ingress/storage limits and live cloud validation are deployment responsibilities; the app still has no built-in authentication or tenant isolation.

## Source scope

Local research includes ten text extracts and 54 illustrative examples, never automatically approved rules. The user uploaded the 75-page original Ulta guide. Walmart material is secondary packaging, not full routing coverage. Michaels still needs its referenced routing/label manual. Supporting documents and guide authority need human review; dates and authority are not inferred from upload time.

### Operational rule delivery (rule schema 1.1)

Operational category and explicit consumption points are independent of rule purpose and verification. The four categories are warehouse operations, transportation/scheduling, electronic documents/EDI, and business administration. Consumers request approved immutable release rules for their specific workflow (for example mobile packing versus ASN generation). The review UI, AI extraction, draft backfill, corrections, exact comparisons, and exports carry this metadata. Missing legacy routing is visible and blocks new approval/publication; published data is never silently backfilled. See `docs/workflow.md` for semantics and the consumer endpoint.

## Standard verification contracts

Rule schema 1.2 adds the shared, versioned `standard_check` catalog. The builder and extraction prompt use the same API-owned definitions and typed parameters. Measurement checks execute with the existing evaluator; other initial automatic contracts are visibly unavailable until implemented. Unmatched shipment requirements need a mapping or an explicit `reference_only` execution mode before approval. Reference requirements preserve shipment purpose, source scope and exceptions, cannot execute or request confirmation/warning/blocking, and never imply compliance. Legacy rules remain readable without implicit migration. See [workflow.md](workflow.md#shared-verification-catalog-schema-12) for contracts and limitations.

## Automatic rule preparation and review readiness

Checks run in two checkpointed passes. First, the configured analysis provider proposes source-backed changes to pending drafts using cited pages, adjacent context and a bounded search for related source pages. Exact quotations and full rule contracts are validated locally. Jev independently verifies each changed field. Only a fully verified proposal preserving obligation, subject, custom assertions, existing bindings and existing workflow placements can apply automatically; new placements must be enabled and display-only. Every applied edit increments the revision, clears prior readiness and records before/after values, citations and the requesting actor in history. Concurrent edits, decisions and cancellation take precedence. Unverified or protected changes remain reviewable proposals.

The second pass checks the prepared rules and possible duplicates against the final draft definitions. This avoids invalidating early results as later rules change. Generic model concerns without a verified, specific correction are questions for review; unavailable shipment automation is reported separately from source accuracy. Original evidence, visual inspection needs and unresolved policy are preserved. Approval, duplicate removal and publication remain explicit decisions. Old assessment versions need a fresh run; aggregate completion is shown separately from the last retry's count. Model and retrieval quality require live acceptance evaluation; synthetic contract tests do not establish accuracy.

## Normalized consumer delivery

Optional, versioned rule-type bindings and validated workflow-area placements extend existing rule records without migrating stored rules. A shared catalog supplies stable semantics across retailers and conservative display defaults. Verification parameters stay in the typed check catalog; consumer enablement and display/confirmation/warning/blocking behavior are distinct from retailer obligation and approval. Read-only delivery resolves an explicitly selected release against canonical facts, retaining unknown scope and unavailable data as needs-information outcomes. Legacy consumer reads remain compatible. The editor, review filters/details, AI extraction, exports and published-release delivery preview expose these contracts. See [workflow.md](workflow.md#standard-rule-types-and-workflow-delivery) for consumer integration semantics and limits.

## Document organization

Retailer → guide series → immutable document edition → analysis/rule draft. Publication produces a combined retailer ruleset rather than activating a PDF upload. Guide-series identity is explicit at upload; updates never infer lineage from file names. See workflow.md for edition comparisons, protected contributions from separate guides, and conflict-review limits.
