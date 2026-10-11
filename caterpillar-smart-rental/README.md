# FleetSignal — Fleet Telemetry and Rental Operations

FleetSignal gives a Caterpillar dealer a fleet dashboard, explainable alerts, rental lifecycle tracking, and demand allocation recommendations. Its backend accepts identified telemetry events, reconciles alerts in the same SQLite transaction, and makes retries safe when a sender loses the response.

The seven-asset demonstration preserves the original SRTS story: recover the idle excavator **EQX1007** for S003, review overdue EQX1002, and inspect live safety telemetry on EQX1004. The dataset and forecast are historical synthetic examples, evaluated at the fixed business clock **2025-05-12**; they are not current fleet observations or validated savings estimates.

## Stack and scope

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic 1.13.2 |
| Storage | File-backed SQLite; one writer, finite busy timeout |
| Dependency management | uv 0.13.0 and `backend/uv.lock` |
| Frontend | React, Vite, existing charts and maps; Node 22.19.0 |
| Local packaging | Docker Compose with persistent named SQLite volume |

This is a single-instance reliability demonstration. It has synchronous alert evaluation and request-driven UI refresh. An optional AWS EC2 deployment is defined below; live AWS deployment has not been verified. PostgreSQL, streaming, authentication, machine learning, and production scale are outside this implementation.

## Local backend

From this project directory, enter `backend`. Install uv and Python 3.11 if needed, then use the committed lockfile:

```bash
cd backend
uv sync --frozen --extra dev
uv run --frozen python -m app.migrations
uv run --frozen uvicorn app.main:app --reload
```

Startup runs the same validated migrations automatically. `GET http://localhost:8000/health` returns `{"status":"ok","service":"FleetSignal Backend"}`. `GET /ready` verifies database connectivity and the required schema revision. OpenAPI is at <http://localhost:8000/docs>.

**Default mode has no demo seed.** `/admin/seed`, `/admin/reset`, and `/assets/{asset_id}/simulate` are absent unless `FLEETSIGNAL_DEMO_MODE=true`. An empty default database therefore has no assets. Existing configured database contents remain available.

To run the historical seven-asset demo, set the environment variable before starting the backend:

```bash
# POSIX shell, from backend/
FLEETSIGNAL_DEMO_MODE=true uv run --frozen uvicorn app.main:app --reload
```

```powershell
# PowerShell, from backend/
$env:FLEETSIGNAL_DEMO_MODE = 'true'
uv run --frozen uvicorn app.main:app --reload
```

From the project root, the equivalent server command is:

```bash
uv run --project backend --frozen uvicorn app.main:app --app-dir backend --reload
```

Both working directories resolve the same absolute defaults: `<project>/.fleetsignal/fleetsignal.db` and `<project>/data`. Importing the app does not create or modify the database; startup owns migration and optional seed work. The original `backend/srts.db` is not selected by default.

## Configuration

| Variable | Default / requirement |
|---|---|
| `FLEETSIGNAL_DATABASE_URL` | Absolute file SQLite URL for `<project>/.fleetsignal/fleetsignal.db` |
| `FLEETSIGNAL_DATA_DIR` | Absolute `<project>/data` directory |
| `FLEETSIGNAL_DEMO_MODE` | `false`; opt in to seed/reset/simulation |
| `FLEETSIGNAL_SQLITE_BUSY_TIMEOUT_MS` | `5000`; positive, at most `60000` |
| `FLEETSIGNAL_ALLOWED_ORIGINS` | Explicit localhost/127.0.0.1 origins on 5173 and 4173, JSON list |
| `SRTS_DEMO_DATE` | Preserved business-clock override; default `2025-05-12` |

Example SQLite URLs: `sqlite:///D:/Projects/FleetSignal/caterpillar-smart-rental/.fleetsignal/fleetsignal.db` on Windows, `sqlite:////absolute/path/fleetsignal.db` on POSIX. Relative paths, memory SQLite, and other database engines are rejected. Every SQLite connection enables foreign keys and a finite busy timeout; WAL is not enabled by this project.

`.env.example` documents these values; the backend does not automatically load `.env`. When supplying absolute-path examples, replace them with your own paths. You may copy it to project `.env`, select demo mode there, and explicitly load it from `backend/`:

```bash
uv run --frozen uvicorn app.main:app --reload --env-file ../.env
```

## Frontend

In another terminal, from the project directory:

```bash
cd frontend
npm ci
npm run dev
```

Use Node **22.19.0**. The app opens at <http://localhost:5173> and uses the real API at <http://localhost:8000> by default. Enable backend demo mode for the existing demo controls and fleet story. `frontend/.env.local.example` documents `VITE_API_BASE` and the separately selected `VITE_API_MODE=mock`; errors do not switch to mock data.

Simulation, check-in, and checkout return after the backend has committed their alert effects. The UI reloads asset/telemetry state afterward. API error messages include a validated request ID when provided by the backend.

## Docker

From the project directory:

```bash
docker compose up --build -d
```

The supplied Compose configuration explicitly enables demo mode. The backend reads data from `/opt/fleetsignal/data` and stores SQLite at `sqlite:////var/lib/fleetsignal/fleetsignal.db`, mounted on the named `fleetsignal_db` volume. Container recreation retains that file; deleting the volume removes its data. For ordinary operation, change `FLEETSIGNAL_DEMO_MODE` to `false` before starting a fresh deployment.

## External telemetry

Send an event for an existing asset. Keep the same global event ID and semantic payload for retries:

```bash
curl -i -X POST http://localhost:8000/telemetry/events \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: demo-ingest-1' \
  -d '{"event_id":"device-EQX1004-0001","asset_id":"EQX1004","timestamp":"2025-05-12T10:00:00Z","engine_temp_c":115,"seatbelt_on":false}'
```

A new event returns **201**; the same validated payload returns **200** with `duplicate=true` and the same telemetry ID. Changed content under that ID returns **409**. Invalid input is **422**, unknown asset **404**, and database contention **503** with `Retry-After: 1`. All responses carry `X-Request-ID`; unexpected errors return a safe **500** response.

One successful transaction stores telemetry and evaluates each alert condition independently. Active episodes retain their ID and creation time. A duplicate does not evaluate alerts or advance their timestamps. `/alerts/refresh` remains an explicit recovery scan; client actions do not depend on it.

## Migrations and existing databases

Use `uv run --frozen python -m app.migrations` from `backend/`. A fresh database upgrades to revision `0002`. An unversioned legacy database is adopted only after validation against the frozen original six-table schema. Revision `0002` preserves legacy telemetry with null event identity/receipt fields and resolves duplicate active alerts while retaining their history; the earliest `created_at`, then lowest ID, remains active.

Back up a legacy file before explicitly configuring its absolute URL for adoption. Unknown schemas are refused without changes; never manually stamp an unknown database to bypass validation. The user's original `backend/srts.db` is not automatically migrated.

## Demonstration and checks

See [the five-minute demo](docs/DEMO_FLOW.md), [API contract](docs/API_CONTRACT.md), and [reliability design and limits](docs/RELIABILITY.md).

From `backend/`:

```bash
uv sync --frozen --extra dev
uv run --frozen pytest -q -p no:cacheprovider
uv run --frozen python scripts/demo_reliability.py
```

The reliability demonstration uses an isolated temporary file database. It shows rollback after an injected exception following a flush, then retry, duplicate, conflict, and retry after a lost response. It does not kill a process or establish process-crash durability.

For an explicitly disposable Docker verification project, start Compose from the project directory, then run the script from `backend/`:

```bash
docker compose -p fleetsignal-verification up --build -d
```

```bash
uv run --frozen python scripts/verify_docker.py --project fleetsignal-verification --base-url http://localhost:8000
```

This verification recreates the named local project's backend container and checks that its data persists. Use that project only for disposable verification.

From `frontend/`, `npm ci` then `npm run build` builds the existing interface. The CI workflow runs locked installs, migrations, backend tests, the frontend build, and the deployment safety harness with Python 3.11 and Node 22.19.0; it needs no external API credentials.

### Verified results

Submission regression: **262 passed in 34.38s**, and **262 in 37.71s** in a clean environment whose configured database hash remained unchanged. The documented setup commands and **13 browser checks** passed. Locked frontend installation and production build passed (660 modules); the targeted dependency fix leaves `npm audit` reporting **zero vulnerabilities**.

The disposable rollback/retry demonstration and fresh Docker ingestion, lock recovery and container recreation checks passed. These establish local operation and named-volume persistence; no cloud deployment was performed.

[SUBMISSION_REVIEW.md](docs/SUBMISSION_REVIEW.md) records the final review, browser/clean-setup results and a three-minute demonstration. [COMPLETION_REPORT.md](docs/COMPLETION_REPORT.md) retains the implementation commands, test counts, Docker evidence and limitations. [Hosted PR verification](https://github.com/reigen002/FleetSignal/actions/runs/38059906165) passed locked installation, migrations, **262 tests in 22.95s**, and the frontend build (660 modules, 551ms). The existing frontend bundle warning above 500 kB remains.

## Optional AWS EC2 demo (not yet live-verified)

The files in [`deploy/aws`](deploy/aws) define one EC2 instance and a separate **encrypted 8 GiB gp3 EBS volume**. They reuse `backend/Dockerfile`, its single Uvicorn process on port 8000, SQLite migrations, demo seed, and existing `/health` and `/ready` endpoints. The repository previously had no frontend Dockerfile: the deployment adds a small Node build/Nginx container for the existing React interface. Local Compose and local development commands are unchanged.

Nginx serves the interface on host port **8080** and forwards `/api/…` to `backend:8000/…` on the Compose network. The deployment build sets the already-supported **`VITE_API_BASE=/api`**, configurable through its Docker build argument; it does not use the browser's `localhost:8000`. Both browser and API share one origin, so deployment CORS origins are empty. The backend has no published host port.

The deployment explicitly sets **`FLEETSIGNAL_DEMO_MODE=true`** to seed the seven-asset demonstration and enable `/admin/seed`, `/admin/reset`, and `/assets/{asset_id}/simulate`. Nginx forwards these routes without application authentication. **Demo gating is not authentication:** setting it to `false` removes those controls but leaves telemetry, rental, and alert-refresh writes unauthenticated. Only trusted operators should access this demo through IAM-controlled SSM sessions.

`/srv/fleetsignal` is the EBS mount, persisted in `/etc/fstab` by filesystem UUID. `/srv/fleetsignal/db` binds to `/var/lib/fleetsignal` in the backend; SQLite remains at `/var/lib/fleetsignal/fleetsignal.db`. The setup script matches the EBS volume ID against its NVMe serial, refuses unsupported filesystems/partitions, and formats a blank volume only with an explicit initialization flag. The systemd service requires the mount and checks it before starting Compose. Docker restart policies are disabled so Docker cannot start the app before EBS mounts after reboot. A missing volume fails startup instead of creating a new database on the root disk. AWS documents [stable EBS device identifiers](https://docs.aws.amazon.com/ebs/latest/userguide/identify-nvme-ebs-device.html).

The data volume has both **`DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`**. Root storage is disposable. An independently attached data volume is preserved on instance termination; the commands below explicitly set and verify `DeleteOnTermination=false` too. Retained volumes continue to cost money and are not backups. See AWS's [retention policy](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html), [replacement policy](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-updatereplacepolicy.html), and [EC2 volume retention](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/preserving-volumes-on-termination.html).

### Access and prerequisites

- **No inbound access by default.** No SSH key or ingress on SSH, backend, database, or Docker API ports. Administrate using Systems Manager Session Manager; access the app through its authenticated port-forwarding session. The instance role grants only `ssm:UpdateInstanceInformation` and the four `ssmmessages` channel actions, following AWS's [minimal Session Manager policy](https://docs.aws.amazon.com/systems-manager/latest/userguide/getting-started-create-iam-instance-profile.html). It has no EC2, S3, secrets, or provisioning permissions. IMDSv2 is required, with one metadata hop.
- **Keep `PrivateWebClientCidr` empty for this demo and use SSM forwarding.** The optional rule opens 8080 to one RFC1918 `/32`; it restricts network access and does not authenticate users. Do not enable it on a shared VPN or shared egress address. An isolated private client must be controlled exclusively by trusted operators; public client CIDRs are rejected. Use synthetic demo data. CORS is not authentication. **Public access requires TLS and authentication/authorization for every write route, including admin controls. Those prerequisites are not implemented here; do not open a public ingress rule.** A domain/certificate alone would not secure the write endpoints.
- Supply an existing VPC and subnet in the chosen Availability Zone. This template assigns a public IPv4 for **outbound** HTTPS via the subnet's internet gateway; it does not create a VPC, NAT gateway, or endpoints. Outbound port 443 must reach Amazon Linux repositories, GitHub, container registries, and regional SSM endpoints. The subnet must belong to `VpcId` and match `AvailabilityZone`. Use the supplied x86_64 Amazon Linux 2023 AMI and a supported region with `t3.small` capacity. Docker/Compose/Buildx installation happens in user data; stack creation does not prove that bootstrap or the app is healthy.
- Images are built on the instance. Memory usage during `npm ci` and the Vite build has not been verified on the default `t3.small`. If a live build runs out of memory, use the supported `InstanceType=t3.medium` parameter and account for its higher compute cost; review any change set before updating an existing instance. Do not treat a local Docker build as evidence that the EC2 build will fit.
- On the operator's laptop: AWS CLI v2, the Session Manager plugin, Python 3.11+, and AWS credentials supplied through your normal profile/SSO flow. The operator needs CloudFormation/EC2/IAM provisioning permissions including `iam:PassRole`, SSM public AMI parameter access, session access scoped to this instance and the forwarding document, and permissions for the stop/start/teardown actions below. Keep credentials and account-specific parameters outside the repository. Account session preferences requiring KMS or CloudWatch/S3 logging need corresponding narrowly scoped role permissions before use; this minimal role does not grant them.
- Make a reviewed **40-character source commit containing these deployment files** accessible to EC2 through your approved source distribution path. The example below uses an HTTPS public Git checkout; the current uncommitted files are not available there yet. Publishing source is a separate step, not performed by this implementation. Do not embed a private repository token in commands or user data. Record the source commit, resolved AMI ID, and built image IDs with live evidence; dependency lockfiles and tool versions are pinned, but base image tags and the default AMI alias can receive updates.

### Future provisioning commands — not executed here

These examples use **Bash** (including the EC2 SSM shell). Replace the uppercase placeholders with your own values; run from the application directory, `caterpillar-smart-rental`, on your laptop. **Provisioning incurs charges and requires a separate explicit request.**

```bash
export AWS_REGION=YOUR_REGION
export AWS_PROFILE=YOUR_PROFILE
STACK_NAME=fleetsignal-demo
VPC_ID=YOUR_VPC_ID
SUBNET_ID=YOUR_SUBNET_ID
AZ=YOUR_AVAILABILITY_ZONE

aws sts get-caller-identity --region "$AWS_REGION" --profile "$AWS_PROFILE"
```

Confirm the returned `Account` and `Arn` identify the intended account and operator before continuing. Then run this authenticated, non-provisioning template check with the same region and profile:

```bash
aws cloudformation validate-template --template-body file://deploy/aws/cloudformation.yaml \
  --region "$AWS_REGION" --profile "$AWS_PROFILE"
```

Only after validation succeeds and a separate provisioning step is explicitly authorized, continue:

```bash
aws ec2 describe-subnets --subnet-ids "$SUBNET_ID" \
  --query 'Subnets[0].{Vpc:VpcId,AZ:AvailabilityZone}'
aws cloudformation deploy --stack-name "$STACK_NAME" \
  --template-file deploy/aws/cloudformation.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides VpcId="$VPC_ID" SubnetId="$SUBNET_ID" AvailabilityZone="$AZ" \
    PrivateWebClientCidr=''

INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue | [0]' --output text)
VOLUME_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`DataVolumeId`].OutputValue | [0]' --output text)
printf 'Record outside the stack: instance=%s data_volume=%s\n' "$INSTANCE_ID" "$VOLUME_ID"
aws ec2 wait volume-in-use --volume-ids "$VOLUME_ID"
aws ec2 modify-instance-attribute --instance-id "$INSTANCE_ID" \
  --block-device-mappings '[{"DeviceName":"/dev/sdf","Ebs":{"DeleteOnTermination":false}}]'
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].BlockDeviceMappings'
aws ssm start-session --target "$INSTANCE_ID"
```

Confirm that `/dev/sdf` maps to the recorded `VOLUME_ID` with `DeleteOnTermination: false`. If SSM is not ready, wait for the agent to come online and retry. Inside the EC2 session:

```bash
sudo cloud-init status --wait
sudo docker compose version
sudo docker buildx version
SOURCE_COMMIT=YOUR_REVIEWED_40_CHARACTER_COMMIT_WITH_DEPLOYMENT_FILES
VOLUME_ID=YOUR_RECORDED_DATA_VOLUME_ID
sudo git clone https://github.com/reigen002/FleetSignal.git /opt/fleetsignal-source
sudo git -C /opt/fleetsignal-source checkout --detach "$SOURCE_COMMIT"
cd /opt/fleetsignal-source/caterpillar-smart-rental
sudo bash deploy/aws/setup.sh "$VOLUME_ID" --initialize-empty-volume
sudo systemctl status fleetsignal --no-pager
sudo docker compose -f deploy/aws/compose.yaml ps
findmnt /srv/fleetsignal
curl --fail http://127.0.0.1:8080/api/ready
sudo docker compose -f deploy/aws/compose.yaml images
```

Only pass `--initialize-empty-volume` for the stack's new blank volume. For retained data, omit it. The script never reformats an existing filesystem. On failure inspect `sudo tail -n 100 /var/log/cloud-init-output.log`, `sudo journalctl -u fleetsignal -n 100 --no-pager`, and `sudo docker compose -f deploy/aws/compose.yaml logs --tail 100`. Do not bypass a failed mount or reset the database to make readiness pass.

### Exact live verification sequence — not performed on AWS here

Keep the demo idle during this sequence; concurrent writes or resets would invalidate the saved alert comparison. In a separate laptop terminal, leave this session running:

```bash
aws ssm start-session --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}'
```

1. **Startup and health:** On the laptop, `curl --fail http://localhost:8080/`, `curl --fail http://localhost:8080/api/health`, and `curl --fail http://localhost:8080/api/ready`. Open `http://localhost:8080` in the browser and confirm the seven assets load from `/api/assets` in the network panel; an asset detail deep link should also load. On EC2, the Compose backend must be healthy and `findmnt /srv/fleetsignal` must show the data volume's UUID.
2. **Telemetry, duplicate, and alert proof:** From the application directory on the laptop run:

   ```bash
   python deploy/aws/verify_api.py record --state .tmp/aws-proof.json
   ```

   This checks health/readiness, sends one unique telemetry event for `EQX1001` with engine temperature 115°C and an unfastened seatbelt, requires **201**, checks `engine_overheat` and `seatbelt_violation` through `GET /api/alerts`, and retries the identical event. It requires **200**, `duplicate=true`, the same telemetry ID, exactly one telemetry row, and unchanged alert IDs/timestamps. The state file stays on the laptop. Treat every failed assertion or HTTP error as a failed verification.
3. **Application container persistence:** In the EC2 SSM shell run `sudo systemctl restart fleetsignal`. This stops and recreates the app containers against the same EBS bind. On the laptop run:

   ```bash
   python deploy/aws/verify_api.py check --state .tmp/aws-proof.json
   ```

4. **EC2 stop/start persistence:** On the laptop, with the AWS variables above still set:

   ```bash
   aws ec2 stop-instances --instance-ids "$INSTANCE_ID"
   aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"
   aws ec2 start-instances --instance-ids "$INSTANCE_ID"
   aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID"
   ```

   Stop/start disconnects SSM sessions and may change the public IPv4. Reopen the admin session and the same forwarding command after SSM is online. On EC2 run `findmnt /srv/fleetsignal`, `sudo systemctl status fleetsignal --no-pager`, and `sudo docker compose -f /opt/fleetsignal-source/caterpillar-smart-rental/deploy/aws/compose.yaml ps`. Then on the laptop run `python deploy/aws/verify_api.py check --state .tmp/aws-proof.json` again. **No manual application start should be needed.** This must retain the original telemetry ID, one row, and saved alerts. Save timestamps, outputs, source commit, image IDs, and volume ID as evidence; this is the required live persistence proof.

### Cost, shutdown, retention, and replacement

**EC2, EBS (including retained/root volumes and snapshots), public IPv4, and data transfer may incur charges.** This is not a free-tier claim. Stopping EC2 pauses ordinary on-demand compute charges but EBS remains billable; an automatically assigned public IPv4 is released on stop. Restarting resumes compute charges. See AWS [EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/) and [EBS pricing](https://aws.amazon.com/ebs/pricing/).

To pause compute, run `aws ec2 stop-instances --instance-ids "$INSTANCE_ID"` and `aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"`. To delete the stack while preserving data, first record its `VOLUME_ID`. In the EC2 SSM shell stop the app and unmount cleanly:

```bash
sudo systemctl disable --now fleetsignal
cd /opt/fleetsignal-source/caterpillar-smart-rental
sudo docker compose -f deploy/aws/compose.yaml down --timeout 30
sudo umount /srv/fleetsignal
```

Then on the laptop:

```bash
aws ec2 stop-instances --instance-ids "$INSTANCE_ID"
aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"
aws cloudformation delete-stack --stack-name "$STACK_NAME"
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
aws ec2 describe-volumes --volume-ids "$VOLUME_ID" \
  --query 'Volumes[0].{State:State,Encrypted:Encrypted,Attachments:Attachments}'
```

The instance, disposable root volume, security group, instance profile, and role are deleted. The **data volume survives, remains billable, and is no longer managed by the deleted stack**. Creation rollback can also leave a retained volume; inspect stack events/resources and your tagged volumes after failed provisioning. Check that the retained volume is `available` with no attachments. Never force-detach a mounted database volume; AWS documents [unmounting before attachment removal](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ec2-volumeattachment.html).

Optional backup, and **separate irreversible cleanup** when the data is no longer needed:

```bash
SNAPSHOT_ID=$(aws ec2 create-snapshot --volume-id "$VOLUME_ID" \
  --description 'FleetSignal demo after clean shutdown' --query SnapshotId --output text)
aws ec2 wait snapshot-completed --snapshot-ids "$SNAPSHOT_ID"
# Only after checking the recorded volume ID, snapshot, and absence of attachments:
aws ec2 delete-volume --volume-id "$VOLUME_ID"
# Only when the snapshot is also no longer needed (otherwise it remains billable):
aws ec2 delete-snapshot --snapshot-id "$SNAPSHOT_ID"
```

**Instance replacement is a deliberate recovery operation, not automatic failover.** Keep the AZ and volume fixed. Review a CloudFormation change set before any replacement, stop the app and unmount before attachment changes, and ensure the old instance is stopped/detached before attaching the same volume to a new instance. A retained volume cannot be attached across AZs; retain/snapshot it and explicitly recover rather than silently accepting a fresh empty database. A fresh stack creates a new volume, not a restore. Recovering after stack deletion requires importing the recorded volume or explicitly attaching it to replacement compute and running `setup.sh` without the initialization flag. Never run two writers against the same SQLite file. This demo does not establish high availability, horizontal scaling, backup recovery, or EC2 replacement automation.

### Local deployment checks and evidence limits

From the application root:

```bash
docker compose -f deploy/aws/compose.yaml config --quiet
uvx --from cfn-lint cfn-lint deploy/aws/cloudformation.yaml
bash -n deploy/aws/setup.sh
python deploy/aws/test_deployment.py
```

`test_deployment.py` requires Python 3.11+ and running Docker with Linux containers. It checks 27 valid/invalid CIDR inputs and 14 mocked formatting and mount safety cases against the actual `setup.sh`, including matching/wrong mounted UUIDs, a non-empty unmounted directory, and a conflicting fstab entry. It may download `python:3.11-slim`, the backend's existing base image. Disk checks use a disposable container with networking disabled, read-only root/repository mounts, and temporary tmpfs paths. Only the `MKNOD` capability is enabled for a fake block-device node; no host devices are passed through. Formatting, disk discovery, mounting, Docker, and systemd commands are stubbed. These checks do not format a real disk, contact AWS, or establish EBS persistence.

The [`deployment` CI job](../.github/workflows/fleetsignal.yml) runs this harness on Ubuntu with Python 3.11 for pushes and pull requests touching the application or workflow, alongside the existing backend/frontend jobs. A failed assertion fails the job. Require the `deployment` status check in the target branch's protection rules or ruleset before merging deployment changes; adding a workflow alone does not enforce that requirement. Hosted execution and repository protection settings have not been verified here. This job uses no AWS credentials and does not replace authenticated template validation or live EC2/SSM/EBS checks.

Run the existing backend suite and frontend locked install/build as documented above. To check the deployment frontend configuration locally, build with `VITE_API_BASE=/api VITE_API_MODE=real npm run build` from `frontend/`. `npm run lint` is also available. `cfn-lint` is local schema/intrinsic validation; it does not establish AWS IAM access, subnet routing, bootstrap success, or persistence. `aws cloudformation validate-template` is an additional future authenticated API check; it does not provision resources.

AWS template validation attempt (2026-10-11): `uvx --from awscli aws cloudformation validate-template --template-body file://deploy/aws/cloudformation.yaml` exited 1 with `You must specify a region.` The temporary CLI stopped before calling CloudFormation. Supply your chosen region and authenticated profile and rerun validation before provisioning; AWS acceptance of this template remains unverified.

**Live AWS provisioning, EBS formatting/mounting, Session Manager access, and EC2 stop/start persistence have not been performed by this implementation.** Complete the sequence above before claiming cloud deployment evidence.

Local implementation verification (2026-10-11): **262 backend tests passed in 39.59s**; the existing isolated rollback/retry demonstration passed. Locked frontend installation reported zero vulnerabilities; ordinary and `/api` production builds passed (660 modules). Lint exited successfully with two existing warnings in untouched files; the Docker frontend build retains the existing bundle-size warning. Deployment Compose validation, `cfn-lint 1.57.2`, `actionlint 1.7.12` on the updated workflow, Bash syntax checks for setup/user data, 27 CIDR cases, and 14 mocked formatting and mount safety cases passed. A disposable local Docker project used a separate `.tmp` SQLite bind and loopback port 18080: frontend/SPA serving, real `/api` routing, health/readiness, 201 ingestion, 200 duplicate handling, alerts, and persistence after backend restart and both-container recreation passed. The served bundle had no `localhost:8000` API URL. These are **local Docker checks, not EBS or EC2 persistence checks**.

Resume bullet — **usable only after live deployment and persistence checks pass**:

> Deployed FleetSignal on AWS EC2 using CloudFormation and Docker Compose, restricted administration to Systems Manager, and verified idempotent telemetry ingestion, alert reconciliation, and SQLite persistence on encrypted retained EBS across container recreation and EC2 stop/start.

## Historical documents

[HACKATHON_SPEC.md](docs/HACKATHON_SPEC.md) and [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) preserve the original hackathon requirements and design. Their original SRTS branding, setup assumptions, and scope are historical; use this README and the active API/reliability documentation for current behavior.

Utilization still reports two explainable measures: productive ratio `engine / (engine + idle) × 100`, and shift utilization `engine / (operating days × 8 hours) × 100`, capped at 100. Telemetry ingestion preserves the existing rental metrics, forecast method, recommendation logic, and business clock.
