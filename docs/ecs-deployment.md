# ECS POC deployment

## One image, one service, two containers

Build the repository-root `Dockerfile`, target `production`. It contains the built React UI,
FastAPI, Poppler, and the worker. Nginx and a separate frontend image are not needed.
Local Compose/Vite remains available for development.

Provision one ECS Fargate service, desired count **1**, with one task containing:

| Container name | Command | Network |
| --- | --- | --- |
| `api` | Image default: `uvicorn routing_guides.api:app --host 0.0.0.0 --port 8000` | ALB target, HTTP port **8000** |
| `worker` | `python -m routing_guides.worker` | No port mapping or ALB target |

Both use the **same image digest** and are essential containers. Use `awsvpc`, Linux/X86_64
(the workflow builds `linux/amd64`), and `initProcessEnabled=true`. Start with 2 vCPU / 4 GB
for the task and measure PDF-processing resource usage. Set worker `stopTimeout=120`.
Deployments may briefly overlap workers; PostgreSQL queue locks serialize jobs.
Saved responses and checkpoints allow interrupted analysis to resume.

## ALB and container health

- ALB target: `api:8000`, target type `ip`.
- ALB health check: **`/api/health/ready`**, matcher **200**; returns 503 for database failure.
- API container health check: `CMD`, `python`, `-c`,
  `import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3)`.
- Worker container health check: `CMD`, `python`, `-m`, `routing_guides.worker_health`.
  Checks a container-local heartbeat refreshed after successful database heartbeats.
- Suggested timing: interval 30s, timeout 5s, retries 3, start period 60s; ECS health-check
  grace period 60s. Enable the ECS deployment circuit breaker with rollback.
- `/api/health/live` is also available for basic API liveness.

Use HTTPS at the ALB and internal access/your existing SSO layer; the app does not implement
login or user authorization. The browser uses same-origin `/api` URLs: no frontend env vars
or API keys. Allow sufficient upload time for PDFs (default file limit 256 MB). File-size
validation occurs after multipart parsing; account for upload spooling in task ephemeral disk
and ingress limits.

## Secrets and application settings

Inject these Secrets Manager values into **both containers** using ECS `secrets`:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require
ANTHROPIC_API_KEY=...
JEV_API_KEY=...
```

URL-encode special characters in the DB username/password. The URL is one secret; separate
username/password environment variables are not consumed. PostgreSQL 17 is used locally and
in CI. Bootstrap needs permission to create/alter application tables and the queue schema.

The production image sets `CREDENTIALS_MODE=environment`: provider credentials come only
from injected env values. Connections shows managed status, rejects credential changes, and
ignores local `connections.json` credentials. Secrets never enter PostgreSQL or browser responses.
Rotate secrets through Secrets Manager and redeploy the task to receive new values. Optional
future integrations use `OPENAI_API_KEY` and `SHIPHERO_ACCESS_TOKEN`.

**No model or upload-limit env vars are required.** These preferences live in PostgreSQL and
are editable in Connections. Fresh defaults: Anthropic `claude-opus-5-5`, Jev `jev-1.14.0`,
OpenAI unset, upload limit 256 MB. Provider account access still needs verification. Existing
analysis runs retain their selected model. Bootstrap imports existing non-secret environment/file
preferences once; later deployments never overwrite DB preferences.

Local development retains editable credentials in `/data/connections.json` (mode 0600).
No automatic copying of local credentials into AWS or PostgreSQL occurs.

## Storage and networking

Mount the **same EFS access point at `/data` in both containers**, writable by UID/GID
**10001:10001**, with transit encryption. This stores originals, page images/text and saved
provider responses. Default `STORAGE_ROOT=/data` needs no override. Rules, preferences and the
job queue live in PostgreSQL. No Redis or separate queue service is required.

Allow task access to PostgreSQL, EFS, ECR/CloudWatch/Secrets Manager and outbound HTTPS to
Anthropic and Jev. Use `awslogs` for both containers. Back up PostgreSQL and EFS together.

## GitHub Actions and Terraform ownership

- `ci.yml`: frontend build/tests, backend tests against disposable PostgreSQL, deployment-script
  tests, production image build, and an isolated upload/worker/settings smoke test.
- `deploy.yml`: manually dispatched from `master`; runs CI, uses AWS OIDC, pushes an immutable
  tagged image to ECR, runs migrations, and updates ECS using its digest. Deployment is serialized.
  Failed migrations prevent service updates; rollback is reported as failure, not success.
- The deployment script clones the service's active task definition, preserving secrets, mounts,
  roles, logging and resources, and updates both image references.
- **Terraform owns infrastructure; GitHub Actions owns application task revisions.** Set
  `lifecycle { ignore_changes = [task_definition] }` on `aws_ecs_service` to avoid rolling back
  application releases on Terraform apply. Infra task configuration changes must be deliberately
  activated on the service before the next application deployment, which clones that definition.

Configure these variables on the GitHub **`poc` environment**:

| Variable | Value |
| --- | --- |
| `AWS_REGION` | Region |
| `AWS_DEPLOY_ROLE_ARN` | OIDC-assumable deployment role |
| `ECR_REPOSITORY` | Repository name, e.g. `parse`, not a full URL |
| `ECS_CLUSTER` | Cluster name or ARN |
| `ECS_SERVICE` | Service name |

Restrict the `poc` environment to `master`; scope OIDC trust to this repository/environment.
The deployment role needs ECR login/push; ECS describe/register/run/stop tasks and update/describe
service; and `iam:PassRole` for the task/execution roles, scoped to ECS. It does not need access
to application secret values. The execution role needs ECR pull, logs, secrets and applicable
KMS access. EFS IAM access, if enabled, belongs on the task role.

### First deployment

1. Create the GitHub repo, add this source, configure OIDC + variables, and create ECR.
2. Run **Publish and deploy ECS** with `deploy=false` to obtain an image digest in its summary.
3. Infra provisions the service/task above with that image and desired count **0**, plus ALB,
   database, secrets, storage and health checks.
4. Change Terraform's desired count to **1** in configuration without applying a premature start.
   Run the workflow with `deploy=true`: it migrates first, then starts the service at count 1.
5. Verify upload → preparation → analysis → review in the deployed environment.

The migration command is `python -m routing_guides.bootstrap`. The workflow runs it as a
temporary single-container task with the API's secrets, mounts and networking, and checks its
exit code before deploying. It is not another persistent service. Migrations use a PostgreSQL
advisory lock. Use additive, backwards-compatible migrations while older tasks remain live.
Image rollback does not undo schema migrations.

AWS deployment has not been executed locally. Infra must supply ECR/OIDC/service identifiers.
Local builds do not create a remote repo or cloud resources.

Run `make check-production` locally to build the single image and exercise it with disposable
PostgreSQL and document storage. The smoke test cleans up its own containers, network and volumes;
it never uses local guide records, credentials or provider API calls.
