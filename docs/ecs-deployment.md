# ECS POC deployment

## One image, one service, two containers

Build the repository-root `Dockerfile`, target `production`. It contains the built React UI,
FastAPI, Poppler, and the worker. Nginx and a separate frontend image are not needed.
Local Compose/Vite remains available for development.

Provision one ECS Fargate service, desired count **1**, with one task containing:

| Container name | Command | Network |
| --- | --- | --- |
| `parse` | Image default: `uvicorn routing_guides.api:app --host 0.0.0.0 --port 8000` | ALB target, HTTP port **8000** |
| `worker` | `python -m routing_guides.worker` | No port mapping or ALB target |

Both use the **same image digest** and are essential containers. Use `awsvpc`, Linux/X86_64
(the workflow builds `linux/amd64`), and `initProcessEnabled=true`. Start with 2 vCPU / 4 GB
for the task and measure PDF-processing resource usage. Set worker `stopTimeout=120`.
Deployments may briefly overlap workers; PostgreSQL queue locks serialize jobs.
Saved responses and checkpoints allow interrupted analysis to resume.

## ALB and container health

- ALB target: `parse:8000`, target type `ip`. Local Compose still names this container `api`;
  the deployment script supports either name alongside `worker`.
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

Inject these SSM Parameter Store (or Secrets Manager) values into **both containers** using ECS `secrets`:

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
Rotate secrets through the configured secret store and redeploy the task to receive new values. Optional
future integrations use `OPENAI_API_KEY` and `SHIPHERO_ACCESS_TOKEN`.

**No model or upload-limit env vars are required.** These preferences live in PostgreSQL and
are editable in Connections. Fresh defaults: Anthropic `claude-opus-5-5`, Jev `jev-1.14.0`,
OpenAI unset, upload limit 256 MB. Provider account access still needs verification. Existing
analysis runs retain their selected model. Bootstrap imports existing non-secret environment/file
preferences once; later deployments never overwrite DB preferences.

Local development retains editable credentials in `/data/connections.json` (mode 0600).
No automatic copying of local credentials into AWS or PostgreSQL occurs.

## Storage and networking

Mount the **same EFS access point at `/data` in both containers**, with transit encryption.
The container runs as UID/GID **10001:10001**; the dev access point enforces **1000:1000**
and owns its `/data` root with mode 0755. EFS applies that access-point identity to file
operations, so it does not require changing the container UID. This stores originals, page images/text and saved
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
- By default, the deployment script clones the service's active task definition, preserving secrets,
  mounts, roles, logging and resources, and updates both image references. For the first deployment
  over an infra placeholder, select `configure_task=true` to use `deploy/dev-task-definition.json`.
  This deliberately replaces the task configuration; leave it unchecked for normal image releases.
  Both paths migrate before updating the service, and reuse its existing subnets/security groups.
  The configured family must match the current task family and the service ALB mapping must match
  a container/port in the new task; mismatches stop before any AWS writes.
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
to application secret values. The execution role needs ECR pull, logs, `ssm:GetParameters` for the
three app parameters (or Secrets Manager access when using that store), and `kms:Decrypt` when
using a customer-managed KMS key. EFS IAM access, if enabled, belongs on the task role.

### Supplied dev infrastructure

The following values were supplied by infra and verified through read-only AWS calls on
October 26, 2026; they are identifiers, not secret values. The checked-in task template uses these resolved role
and EFS identifiers. Their SSM parameter ARNs cannot be placed directly in `taskRoleArn`,
`executionRoleArn`, or EFS ID fields; those fields require the parameter **values**.

| GitHub `poc` variable | Value |
| --- | --- |
| `AWS_REGION` | `us-east-1` |
| `ECR_REPOSITORY` | `parse-dev` |
| `ECS_CLUSTER` | `internal-tooling-dev` |
| `ECS_SERVICE` | `dev-parse` |
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::789248412670:role/github_oidc_ecs_deployments` |

GitHub environment `poc` and its five variables were configured on October 26, 2026,
with a branch policy allowing `master`. No workflow was dispatched.

The template contains API and worker containers, port 8000 on the API, both health checks,
CloudWatch log group `/ecs/dev-parse`, and an encrypted shared `/data` EFS mount. The image
field is a placeholder replaced by the workflow's newly built ECR digest; do not register the
template unchanged. Task resources start at 2 vCPU / 4 GiB, as described above.

Secrets are referenced by ARN, never downloaded into the repo or GitHub:

```text
arn:aws:ssm:us-east-1:789248412670:parameter/parse/dev/DATABASE_URL
arn:aws:ssm:us-east-1:789248412670:parameter/parse/dev/ANTHROPIC_API_KEY
arn:aws:ssm:us-east-1:789248412670:parameter/parse/dev/JEV_API_KEY
```

Non-secret infrastructure parameter names (account `789248412670`, region `us-east-1`):

| Parameter | Supplied value used in template |
| --- | --- |
| `/dev/parse/exec_role` | `arn:aws:iam::789248412670:role/dev-parse-exec` |
| `/dev/parse/task_role` | `arn:aws:iam::789248412670:role/dev-parse-task` |
| `/dev/parse/efs/access_point/shared` | `fsap-0f9cda99261722299` |
| `/dev/parse/efs/file_system_id` | `fs-0e62adad061f3b99a` |

Read-only inspection found the existing service running one nginx placeholder task. Its ALB
already targets `parse:8000`, with a 60-second grace period and rollback circuit breaker enabled.
The template retains that container name. The current placeholder has 0.5 vCPU / 1 GiB; the
prepared app template increases this to 2 vCPU / 4 GiB for PDF processing. No AWS resource was
modified during inspection.

The three secret parameters exist as `SecureString` using `alias/aws/ssm`; their values were
not retrieved. EFS enforces user/group 1000, the task role grants mount/write on this access
point, and the security groups allow NFS between the task and EFS. Actual database access,
provider credentials, EFS writes and application behavior have not been exercised in AWS.

Remaining infra setup before the first run:

- The GitHub deployment role trusts audience `sts.amazonaws.com` and subject
  `repo:Shiphero@5844322/parse@1431158881:environment:poc` using the account's GitHub OIDC provider, with the
  deployment permissions described above. Infra confirmed `github_oidc_ecs_deployments` as
  the intended role, and its ARN is saved as `AWS_DEPLOY_ROLE_ARN`. Infra still needs to add
  `Shiphero/parse` to that role's trust policy; the earlier inspection showed it absent.
  The repository's OIDC settings report `use_immutable_subject=true` and prefix
  `repo:Shiphero@5844322/parse@1431158881`; the older name-only subject will not match.
- Add `ecs:RunTask`, `ecs:DescribeTasks`, and `ecs:StopTask` for migration tasks to that
  deployment role. Its inspected policy includes ECR push, task registration, service updates
  and `iam:PassRole`, but omits these migration operations.
  `deploy/dev-deployment-migration-policy.json` contains a proposed addition scoped to the dev
  cluster and migration task family. ECS task ARNs do not encode task family, so Describe/Stop
  are scoped to tasks in `internal-tooling-dev`; infra can refine this with a tagging design.
- Change the `parse-dev` target group's health path from `/` to `/api/health/ready`, HTTP 200,
  coordinated with the first app rollout: nginx does not serve the app's readiness endpoint.
  These ALB settings belong in Terraform, not the task definition.
- Add `ssm:GetParameters` on the three app secret ARNs to `dev-parse-exec`. Its current policy
  covers logs and ECR only. `deploy/dev-execution-ssm-policy.json` is the minimal policy addition
  for infra to apply through Terraform. The current secrets use the AWS-managed SSM key; if
  moved to a customer-managed key, also provide the applicable `kms:Decrypt` permission.
- Verify EFS mount targets, database access and outbound provider connectivity from the task
  subnets. Security-group inspection alone does not prove end-to-end connectivity.
- Terraform will not overwrite application task revisions, and its desired count is coordinated
  with the first deployment. The workflow runs migrations before replacing the running nginx
  placeholder; it does not require stopping that existing placeholder first.

Once ready, run **Publish and deploy ECS** from `master` with `deploy=true` and
`configure_task=true`. The workflow replaces the placeholder configuration, migrates, then
starts the service. Subsequent releases use `deploy=true`, `configure_task=false`.
The configured app hostname is `parse.dev2.shiphero.com`; internal network access and HTTPS
routing still need verification. A passing ECS deployment does not establish a working
upload → preparation → analysis → review flow; verify that separately.

References: [ECS SSM secret injection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-ssm-paramstore.html),
[EFS task configuration](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specify-efs-config.html),
[EFS access-point identity](https://docs.aws.amazon.com/efs/latest/ug/enforce-identity-access-points.html).
See also [GitHub immutable OIDC subjects](https://docs.github.com/en/actions/reference/security/oidc).

### Bootstrapping a new service from scratch

For the existing dev service, follow the first-run instructions above. These steps apply only
when provisioning another service that does not already have a running placeholder.

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
