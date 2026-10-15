# routing-guide-parser

A local application for turning retailer routing guides into reviewed rules and shipment validations. The initial foundation runs a React interface, FastAPI backend, PostgreSQL database and Procrastinate worker in Docker.

## Start locally

Docker Desktop and Docker Compose are required. Python 3 is used only to create the local configuration; application dependencies run inside containers.

```sh
make up
```

Open [the workspace](http://localhost:5180) or [API documentation](http://localhost:8180/docs).

The setup script creates `.env` with a random local database password and preserves existing configuration. No AI credentials are needed to start the app or use manual review and scenarios. Ports bind to `127.0.0.1`; PostgreSQL has no host port. This local setup has no user authentication and must not be exposed to a network.

```sh
make status         # Container status
make logs           # Follow API, worker and frontend logs
make down           # Stop containers; retain data
make up             # Rebuild/start; migrations run before services
make restart-worker # Pick up worker source changes
```

Frontend and API source changes reload during development. Dependency, migration, Dockerfile and build configuration changes require `make up`. The worker must be restarted after source changes. Docker volumes preserve database records and documents across normal stops and rebuilds. Removing volumes deletes their contents; no reset command is supplied.

## What exists

- PDF upload, persistent retailer library, full-page rendering/text extraction and source viewer.
- Configurable Claude and OpenAI adapters with durable page batches, retries, cancellation, coverage and model/usage records.
- Local Connections screen for server-side credentials, with presence-only responses. Jev / TypeSafe is available for classification of existing rules.
- Manual and AI draft review with evidence images, edits, exact-revision approval and audit history.
- Explicit retain/replace/retire update decisions, comparison, scenario impact and immutable releases.
- JSON rule exports, Markdown instructions, release history and active-release restoration.
- Pasted JSON and read-only ShipHero wholesale snapshots, explicit overrides and deterministic evaluations pinned to releases.
- Bounded typed rule expressions, exact unit conversions and explicit unknown outcomes.

Read the [end-to-end workflow](docs/workflow.md) for usage, contracts, integration references and limitations. AI analysis requires a configured provider key/model; ShipHero import requires an access token. Neither integration is claimed live-verified by local tests. Shared authentication, cloud deployment, dedicated OCR, non-PDF ingestion and model-quality benchmarking are not delivered by this local milestone.

## Working with guides

Choose a retailer and upload its original PDF. The worker counts all PDF pages, creates a coverage record for each, then renders page images and extracts available text. Open the guide to inspect completed pages while remaining pages are processed. Pages without embedded text are informational, not preparation failures. Their images are retained for visual analysis; lack of text never establishes lack of requirements. Only failed text extraction or page rendering triggers preparation attention. Automatic OCR is not yet available.

Originals are immutable. Uploading identical bytes for the same retailer returns the existing guide without changing its metadata. Different files remain separate uploads; semantic version comparison is not yet available. Effective dates are entered explicitly and are not inferred from upload dates.

Preparation can be retried after failure; completed page work is retained. The queue recovers jobs left behind by a terminated worker. A configurable `MAX_UPLOAD_MB` (256 MB by default) controls local resource usage and is shown in the upload form; there is no page-count truncation. Poppler operations have per-command timeouts, with failures recorded rather than silently omitted. Upload limits are enforced after multipart spooling in this local build; shared deployment must also limit incoming request size at its gateway.

Document files live in the `documents` Docker volume. Unknown database commit outcomes retain files rather than risk deleting an original that was successfully saved. Orphan-file cleanup and storage quotas are future operational work.

## Configuration

See `.env.example`. Optional environment credentials are `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `JEV_API_KEY`, with separate model settings. Jev defaults to `jev-1.14.0` and supports existing-rule classification; guide extraction uses Claude or OpenAI. Having a key configured does not mean provider access has been verified. Connections in the app override these environment defaults. Keep `.env` out of Git. Recreate API/worker containers after environment changes with `make up`. Service health and provider configuration remain available through the API for developers; they are not the user's homepage.

Change `WEB_PORT` or `API_PORT` in `.env` if needed. The PostgreSQL password must match the existing database volume: changing the environment alone does not rotate an initialized database's password.

## Layout

```text
backend/
  src/routing_guides/   API, config, contracts, persistence and worker
  migrations/          Application database migrations
frontend/
  src/                 React UI and generated API types
docs/
  build-spec.md        Architecture, data model, milestones and scope
scripts/
  setup.py             Non-destructive local configuration
analysis/              Existing discovery report and illustrative inventory
sources/               Existing source manifest and text extracts
```

The [implementation spec](docs/build-spec.md) is the repository reference for the build. The earlier [product plan](https://chatgpt.com/space/page_7951bec4fa8c8191b95d3dab5beb5354) supplies the broader workflow.

## Development conventions

- Branches have no prefix. Do not push without an explicit request.
- Automatically commit substantial, completed changes using the user's configured Git identity, without AI author or co-author attribution. See `AGENTS.md`.
- Run relevant local checks at commit checkpoints, not automatically after edits. Container startup health checks are part of operating the local app.
- Never replace source evidence with inferred facts, convert missing input into a pass, or import the research examples as approved policy.
- Provider-generated output is untrusted data. Provider integrations cannot publish releases or execute generated code.
- Generate frontend API types from FastAPI OpenAPI after API contract changes; do not manually maintain parallel response types.

Type generation command (run with the API online; generated file must be copied out because the development source mount is read-only):

```sh
docker compose exec -T web npx openapi-typescript http://api:8000/openapi.json -o /tmp/api.generated.ts
docker compose cp web:/tmp/api.generated.ts frontend/src/api.generated.ts
```

Procrastinate owns its queue schema. Bootstrap records its package version and stops if it changes; apply the upstream SQL migrations explicitly before updating that record. Application schema migrations use Alembic. Startup never silently resets either schema.

## Deployment direction

Local first, Railway for the first shared deployment, AWS later if needed. Reuse the Python image for API and worker processes. Use a production frontend build, shared object storage, environment-specific routing and internal sign-in before sharing. The included frontend production Docker target is a starting template and is not a deployed or validated Railway configuration.
