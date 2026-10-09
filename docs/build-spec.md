# Routing Guides implementation spec

Status: local guide library and document preparation, October 9, 2026. This document separates delivered behavior from the remaining build.

## Objective

Convert retailer documents into source-backed, reviewed rules that can produce human instructions and deterministic scenario checks. Users review document changes and their operational effects before publishing a new release. Start with Ulta, using Nordstrom, Walmart and Michaels to challenge the model's flexibility.

## Selected architecture

| Layer | Choice | Boundary |
| --- | --- | --- |
| UI | React, TypeScript, Vite | Source viewer, rule review, scenario editing, settings |
| API | FastAPI, Pydantic | Domain operations and versioned contracts |
| Persistence | PostgreSQL 17, SQLAlchemy, Alembic | Relational identities/history plus JSONB rule payloads |
| Jobs | Procrastinate using PostgreSQL | Durable job delivery; separate Python worker |
| Assets | Local Docker volume now; object storage at shared deployment | Immutable originals, page images, excerpts |
| Providers | Application-owned protocol; native adapters next | Claude default; OpenAI alternative; explicit capabilities |
| Runtime | Docker Compose | Web, API, worker, database and one-shot migrations |

One repository, one backend package, separate API and worker processes. No independent microservices. The generated frontend API types come from backend OpenAPI. Python dependencies are frozen in `backend/uv.lock`; frontend dependencies in `frontend/package-lock.json`.

The PostgreSQL queue avoids a second local datastore. Queue migrations are version-gated independently of application migrations. A single migration process completes before API and worker startup. The local API listens at localhost:8180 and UI at localhost:5180. Database access stays on the Compose network. Existing applications are unaffected.

## Current user workflow

The homepage is a guide library, not a development dashboard. Users filter by retailer, search documents, upload a PDF with title/version/effective date, and open its pages beside extracted text. Preparation status and errors reflect stored records. Development milestones and service health belong in repository documentation and diagnostic endpoints.

PDF uploads preserve immutable originals. Same-retailer duplicate content opens the existing record. The database record and preparation job commit together. The worker creates a page coverage ledger before processing, renders each page with Poppler, extracts available text, and saves progress after each page. Original and rendered files use application-generated paths. Downloads return the original file; page previews display rendered images rather than active PDF content.

Pages without text are flagged for inspection, not assumed empty. OCR and AI rule analysis remain unavailable. Retry resumes failed page work without replacing successful artifacts. A periodic recovery task requeues work left by stalled workers. The local upload-size setting is an explicit configurable resource limit, not a document/page truncation policy.

## Foundation retained

- A live retailer catalog and persistent guide library.
- PostgreSQL connection/readiness, persistent retailer records and worker heartbeat.
- A running queue consumer with PDF preparation and maintenance tasks; AI analysis is not yet implemented.
- Initial domain contracts at `/api/contracts` and API documentation at `/docs` on the API service.
- Safe local `.env` creation and placeholders for provider credentials/model choices.

The UI uses real uploads and preparation records. It does not simulate approvals, validations or successful provider connections. A worker heartbeat indicates process availability, not completed document analysis. No application-level integration tests are claimed by startup health. End-to-end PDF upload acceptance remains pending the user-requested test/commit stage.

## Data model to implement

| Entity | Key content and invariant |
| --- | --- |
| Retailer | Stable ID and display name; discovery notes are not operational rules |
| Guide version | Retailer, file hash, source type, effective dates, authority, covered scope and original asset |
| Document asset | Storage key, MIME type, size, hash, parent/source and conversion metadata |
| Page evidence | PDF page index, printed label, text span, optional normalized region and original image |
| Analysis run | Document versions, provider/model, prompt/schema versions, request configuration, stage outcomes, usage and errors |
| Coverage record | Every page/section assigned a processing outcome; unresolved references remain visible |
| Rule revision | Stable rule ID, subject, obligation, applicability, requirement, exceptions, units, instruction and evidence |
| Review decision | Exact revision or change, actor, timestamp, disposition, reason; further edits invalidate approval |
| Rule release | Immutable manifest of approved revisions, explicit coverage, effective applicability and publication audit |
| Scenario snapshot | Raw input, source/account, captured time, local overrides and supplemental evidence |
| Evaluation | Pinned release, evaluator and mapping versions, resolved inputs, per-rule outcomes and explanation |

Current schema 0.1 only defines candidate/evidence/scenario/provider envelopes. It is deliberately incomplete: no published rule or executable-expression contract exists until the semantics below are agreed on using actual examples. Do not store executable expressions as arbitrary strings or run generated code.

## Rule semantics for the next increment

Develop a bounded expression tree for comparison, ranges, existence, allowed values, all/any/not, counts, sums, uniqueness and grouped consistency. Each operator needs explicit types, units, null behavior, supported scope and boundary inclusivity.

Keep obligation separate from verification: required/prohibited/recommended/informational versus data/human/external-evidence/unresolved. Missing data, unsupported automation and unknown applicability produce Cannot determine. Not applicable requires evidence that the applicability condition is false. Execution failures remain errors, not passes.

First reviewed examples should exercise a weight maximum, a dimension condition, carton grouping, an exception, a recommendation and label placement that requires inspection. A textual instruction and automated assertion must express the same approved revision. Exact arithmetic and unit conversion stay in ordinary Python.

Preserve ShipHero's nested packing_layout, identities and distinct destination concepts. Model carton/case quantities explicitly. Never sum parent and child weights or assume one order describes an entire physical load. The raw payload is retained independently from mappings and user overrides. Production ingestion will minimize unrelated personal/contact fields before durable storage.

## Analysis and model interchangeability

The provider contract accepts an analysis task with document asset references, run ID, requested model, prompt/schema version and required capabilities. Results contain candidates, evidence, warnings, usage and an explicit complete/incomplete/failed outcome. Both request and actual returned model identifiers are retained.

Implement native Anthropic and OpenAI adapters behind this protocol. File upload, request shapes, image handling, schema restrictions and errors belong inside each adapter. Capabilities belong to a provider/model combination, not a universal provider flag. An incompatible model selection fails visibly; no silent fallback or loss of page images.

Pipeline stages: ingest immutable original → extract text/layout and render pages → record coverage → analyze coherent sections → reconcile cross-references and exceptions → normalize/validate candidates → review evidence and completeness. Jobs need idempotency, bounded retries, stage checkpoints and cancellation. Whole-guide coverage must be preserved within provider limits; document size limits must reflect actual resources and provider constraints rather than silently truncating input.

An AI rerun creates a fresh draft. It never rewrites published rules. A configured key is not proof of authorization, access, model capability or adapter readiness. Live provider calls are outside this setup increment.

## Review and publication

Display original evidence beside the interpreted rule and resulting operational instruction/check. For an update, show added rules, requirement changes, scope/exception changes, wording-only changes, possible removals and conflicts. Stable identities must survive page movement; uncertain splits/merges require review.

Absence from an extraction is not deletion. A reviewer explicitly retains, supersedes or retires the old rule. Changes are approved individually, then a release is published atomically. Source-bundle precedence and effective dates are reviewed; upload dates do not establish authority. Publication includes coverage boundaries and saved-scenario impact. Preserve previous releases for comparison and rollback.

## API boundaries

Current read-only endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health/live` | Process availability |
| `GET /api/health/ready` | Database connectivity |
| `GET /api/workspace` | Retailer catalog, heartbeat and sanitized provider configuration |
| `GET /api/contracts` | Draft JSON schemas |
| `GET /api/guides` | Paginated library, retailer counts, title search and preparation filters |
| `GET /api/guides/{id}` | Guide metadata, progress and page coverage |
| `GET /api/guides/{id}/original` | Original PDF download |
| `GET /api/guides/{id}/pages/{index}` | Extracted text and page preparation issues |
| `GET /api/guides/{id}/pages/{index}/image` | Rendered page preview |

Current mutations: `POST /api/guides` accepts the original PDF and metadata; `POST /api/guides/{id}/retry` resumes preparation. No rule or release mutation exists yet.

Next endpoint families: guide versions/assets, analysis runs/progress, rule drafts/revisions, comparison/review decisions, release publication/history, scenario snapshots/overrides/evaluations, and ShipHero read-only import. Mutations need transaction boundaries and repeat-request behavior; publishing requires a revision guard and authenticated actor before multiuser use.

## Build backlog

1. **Executable contracts and scenarios.** Review a small Ulta sample; define operators and normalized scenario fields; implement pasted JSON and deterministic outcomes. Acceptance: explain passing, failing, unknown and non-applicable fixtures without a model call.
2. **AI extraction from prepared documents.** Upload/storage/page viewing and coverage are implemented. Retrieve original retailer PDFs and implement both providers with Claude default. Acceptance: an original Ulta guide yields editable, anchored candidates; interruptions cannot masquerade as complete extraction.
3. **Review and releases.** Add editor, approvals, immutable release, original/new evidence comparison and saved-scenario impact. Acceptance: missing candidates never automatically remove approved rules; prior release remains usable.
4. **ShipHero snapshots.** Fetch a packed order read-only, preserve nesting and distinguish overrides. Acceptance: equivalent pasted and fetched payloads normalize identically; missing evidence produces unknown outcomes.
5. **Provider evaluation and shared use.** Compare reviewed examples across models and retailers; add SSO/roles, account scoping, object storage, backups and deployment configuration. Acceptance: durable work survives restart and permissions constrain publication.

Planned test coverage includes exact boundaries, units, unknown propagation, nested aggregates, evidence integrity, atomic publication, semantic changes, retries and provider failures. Repository tests run when requested to commit. Building containers and starting normal service health checks are setup operations.

## Source prerequisites

Current local research includes ten PDF text extracts, a manifest and 54 illustrative examples. Original PDF downloads failed previously; diagrams and original-page layout remain unverified. Obtain the original Ulta PDF for document work and an authentic same-scope older/newer pair for change acceptance. Synthetic updates can be development fixtures only when clearly marked.

Walmart's material covers secondary packaging rather than all routing requirements. Michaels lacks its referenced full routing/label manual. Supporting Word/Excel files still need conversion and review. Keep these limitations visible when evaluating completeness.

## Deployment path

Local Compose → Railway shared deployment → optional AWS migration. For shared use, build static frontend assets, run the API and worker as persistent services, use PostgreSQL and shared object storage, and add internal authentication. Do not deploy Vite's development server or this unauthenticated local configuration publicly. Container and SQL portability reduces application changes but does not eliminate migration work.

Guides may include business contacts, and order snapshots can include personal data. Keep only necessary fields, keep raw secrets and order payloads out of logs, and run deterministic scenarios without sending order data to an AI provider.

## References

- [Product plan](https://chatgpt.com/space/page_7951bec4fa8c8191b95d3dab5beb5354)
- [Procrastinate quickstart](https://procrastinate.readthedocs.io/en/stable/quickstart.html)
- [Queue schema migrations](https://procrastinate.readthedocs.io/en/stable/howto/production/migrations.html)
- [FastAPI background work](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [ShipHero wholesale flow](https://developer.shiphero.com/flows/wholesale/)
- [ShipHero packing layout](https://developer.shiphero.com/flows/export-packing-layout/)
