---
name: gcp-cloud-run-deploy
description: Use this skill when deploying a containerized app (e.g. a FastAPI service) to Google Cloud Run with a managed Postgres backend (Cloud SQL) and/or a shared Redis cache (Memorystore). Covers exactly which steps are gcloud-CLI-automatable versus which require one-time human setup (auth, billing, IAM grants, security/networking decisions), and the correct command sequence -- including the VPC networking step that connecting to Memorystore actually requires, which is easy to miss.
---

# Deploying to Cloud Run with Cloud SQL + Memorystore Redis

## Mental model

Cloud Run does not run your database or cache as containers alongside your
app. You provision managed services and point your app at them:

- PostgreSQL → **Cloud SQL for PostgreSQL**
- Redis → **Memorystore for Redis**
- Your app → **Cloud Run** (built as a container image)

These two managed backends are NOT symmetric in how Cloud Run reaches them,
and that asymmetry is the part most likely to trip up an automated
deployment:

- **Cloud SQL (public IP)**: reachable via a built-in Unix-socket
  connector. No VPC networking required. Simplest path.
- **Memorystore Redis**: has **no public IP at all**. Cloud Run runs
  outside any VPC by default, so reaching Redis's private IP requires
  bridging the two networks first, via either a Serverless VPC Access
  connector or Direct VPC egress. This is an extra infrastructure step,
  not just an extra env var.
- **Cloud SQL (private IP)**, if you choose that for production, needs
  the same kind of VPC bridging as Redis.

## What genuinely needs a human, once, up front

1. **Initial authentication.** `gcloud auth login` opens an interactive
   browser flow. For agent/CI use, create a service account key once
   (a human with sufficient project permissions does this) and have the
   agent use `gcloud auth activate-service-account --key-file=key.json`
   instead. From that point on, auth is non-interactive.
2. **Billing account + project existence.** Someone with billing
   authority links a billing account to the project at least once.
3. **Sufficient IAM authority for the identity doing the deploying.**
   Granting IAM roles (e.g. `roles/cloudsql.client` to the Cloud Run
   service account) is itself a `gcloud` command -- but the identity
   running that command needs `resourcemanager.projects.setIamPolicy`
   permission (typically Owner or IAM Admin) already. A human with that
   permission either does the grants once, or grants the deploying
   identity enough authority to do its own grants going forward.
4. **Security/networking posture decisions**, made once per project,
   not per deploy: public vs. private IP for Cloud SQL, whether Cloud
   Run allows unauthenticated access, which region, VPC layout.
5. **Cloud SQL connection-limit sizing**: Cloud Run scales from zero to
   many instances, each with its own connection pool. 100 instances x a
   pool of 5 = 500 connections, which can exceed your instance tier's
   limit. Decide max_connections and Cloud Run max-instances together;
   this is a capacity-planning judgment call, not something to automate
   blindly.

Everything else below is scriptable.

## Command sequence

### 1. Auth + project + APIs

```bash
gcloud auth activate-service-account --key-file=key.json
gcloud config set project PROJECT_ID

gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com \
  artifactregistry.googleapis.com \
  vpcaccess.googleapis.com \
  secretmanager.googleapis.com
```

### 2. Cloud SQL for PostgreSQL (public IP path -- simplest, no VPC needed)

```bash
gcloud sql instances create my-db-instance \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=us-central1

gcloud sql databases create issues --instance=my-db-instance

gcloud sql users create appuser \
  --instance=my-db-instance \
  --password=CHOOSE_A_PASSWORD

# Note this down -- it's the identifier Cloud Run needs, format project:region:instance
gcloud sql instances describe my-db-instance --format="value(connectionName)"
```

If you need a **read replica** (matching a master/replica architecture):

```bash
gcloud sql instances create my-db-replica \
  --master-instance-name=my-db-instance \
  --region=us-central1
```

### 3. Memorystore Redis -- the step that actually needs VPC bridging

```bash
# Create the Redis instance (private IP, no public endpoint by design)
gcloud redis instances create my-cache \
  --size=1 \
  --region=us-central1 \
  --tier=basic

REDIS_HOST=$(gcloud redis instances describe my-cache --region=us-central1 --format="value(host)")
REDIS_PORT=$(gcloud redis instances describe my-cache --region=us-central1 --format="value(port)")
REDIS_NETWORK=$(gcloud redis instances describe my-cache --region=us-central1 --format="value(authorizedNetwork)")

# Bridge Cloud Run into that VPC -- pick ONE of the following two options.

# Option A: Serverless VPC Access connector (more broadly supported)
gcloud compute networks vpc-access connectors create redis-connector \
  --region=us-central1 \
  --network=default \
  --range=10.8.0.0/28

# Option B: Direct VPC egress (newer, Google's recommended default for new services)
# No separate connector resource -- pass --network/--subnet directly on `gcloud run deploy`.
```

Skipping this VPC step is the single most common reason a Redis connection
from Cloud Run fails with a timeout -- the instance is unreachable, not
misconfigured.

### 4. Build and push the image

```bash
gcloud artifacts repositories create my-repo \
  --repository-format=docker \
  --location=us-central1

gcloud builds submit --tag us-central1-docker.pkg.dev/PROJECT_ID/my-repo/issues-api:v1
```

### 5. Grant the Cloud Run service account access

```bash
PROJECT_NUMBER=$(gcloud projects describe PROJECT_ID --format='value(projectNumber)')
SA_EMAIL="${PROJECT_NUMBER}[email protected]"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client"

# If using Secret Manager for DB password / Redis auth string:
gcloud secrets add-iam-policy-binding db-password \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"
```

### 6. Deploy to Cloud Run

```bash
CONNECTION_NAME=$(gcloud sql instances describe my-db-instance --format="value(connectionName)")

gcloud run deploy issues-api \
  --image=us-central1-docker.pkg.dev/PROJECT_ID/my-repo/issues-api:v1 \
  --region=us-central1 \
  --add-cloudsql-instances="${CONNECTION_NAME}" \
  --vpc-connector=redis-connector \
  --set-env-vars="DB_HOST=/cloudsql/${CONNECTION_NAME},DB_USER=appuser,DB_NAME=issues,REDIS_HOST=${REDIS_HOST},REDIS_PORT=${REDIS_PORT}" \
  --set-secrets="DB_PASS=db-password:latest" \
  --allow-unauthenticated
```

(`--allow-unauthenticated` is a security decision -- confirm this is
actually what you want before scripting it blindly into every deploy.)

### 7. Verify

```bash
SERVICE_URL=$(gcloud run services describe issues-api --region=us-central1 --format="value(status.url)")
curl "${SERVICE_URL}/health"

gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=issues-api" \
  --project=PROJECT_ID --freshness=5m --limit=50
```

## Common failure modes to check for

- **Redis connection timeout**: almost always the VPC connector/egress
  step was skipped or the connector isn't `READY` yet
  (`gcloud compute networks vpc-access connectors describe redis-connector --region=... `).
- **Cloud SQL socket path errors**: the Unix socket path has a 108-char
  limit on Linux; long project/instance names can exceed it.
- **Connection exhaustion under load**: if Cloud Run scales out
  aggressively, Postgres can hit `max_connections` well before the app
  layer looks unhealthy. Check `gcloud sql instances describe my-db-instance --format="json(settings.tier,settings.databaseFlags)"`.
- **IAM permission denied on deploy**: usually means the identity
  running these commands lacks a role a human needs to grant once
  (see "What genuinely needs a human" above) -- not a bug in the script.