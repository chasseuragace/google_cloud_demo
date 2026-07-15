# Google Cloud Run readiness guide

This document explains how this repository is being prepared for a Google Cloud Run deployment story, even though no real Google Cloud account or credentials are being used here.

## 1. What this repo is trying to show

The repository currently contains a manual distributed demo built around Docker Compose:
- [docker-compose.yml](docker-compose.yml) defines a load balancer, three worker containers, Postgres, and Redis.
- [nginx.conf](nginx.conf) defines the Nginx upstream and routing behavior.

That setup is excellent for learning how load balancing, worker pools, shared caches, and replication work. However, it is not the final Cloud Run model.

Cloud Run changes the deployment story. Instead of manually defining a fixed pool of workers, you deploy a single service and let the platform create and scale instances for you.

## 2. What “ready for Cloud Run” really means

A repo is considered Cloud Run-friendly when the application:
- can start in a containerized environment,
- listens on the port provided by the platform,
- reads configuration from environment variables,
- does not depend on local in-memory state for correctness,
- and can be built and deployed with a standard container pipeline.

This repository is now prepared in that sense, even though the real Cloud deployment step is still a template-only exercise.

## 3. What already helps this repo become Cloud Run-ready

### 3.1 The container can follow the platform runtime contract
The main runtime change is in [app/Dockerfile](app/Dockerfile).

That file now uses the `PORT` environment variable and starts Uvicorn with a dynamic port value instead of assuming a hard-coded `8000` port. This is important because Cloud Run injects its own port at runtime.

Why it matters:
- Cloud Run does not guarantee that your app will always receive port `8000`.
- The platform gives your container a port through the environment.
- The app must bind to that value.

### 3.2 The app can read Cloud-style environment variables
The configuration layer in [app/core/config.py](app/core/config.py) and [app/db/session.py](app/db/session.py) has been adapted so the app can work with both old local-style environment variables and cloud-style values such as `DATABASE_URL` and `DATABASE_URL_READ`.

The example environment file at [app/.env.example](app/.env.example) shows the new shape.

Why it matters:
- In a real Cloud Run deployment, you often receive one main database URL and one read-only database URL from environment variables.
- The service should not break just because the naming convention is slightly different.

### 3.3 The app is structured around externalized state
The application entrypoint in [app/main.py](app/main.py) and the API route layer in [app/api/v1/routes/issues.py](app/api/v1/routes/issues.py) are lightweight. The real application logic is in [app/services/issue_service.py](app/services/issue_service.py).

This is important because Cloud Run instances can restart, scale up, or scale down at any time. The application should not assume that local process memory is reliable for core state.

In this repo, the business behavior relies on:
- the database for persistence,
- Redis for shared cache semantics,
- and environment-based configuration.

That is much closer to the Cloud Run model than a process-local in-memory design.

### 3.4 Deployment scaffolding is already present
The repo now includes deployment-oriented files:
- [cloudbuild.yaml](cloudbuild.yaml) for a Google Cloud Build pipeline.
- [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh) as a deploy template.
- [.gcloudignore](.gcloudignore) for lighter upload content in cloud-based builds.

These files do not deploy anything yet, but they show the expected deployment workflow for a real Cloud Run environment.

## 4. How the repo maps to Cloud Run concepts

### Local Compose concept
In [docker-compose.yml](docker-compose.yml), the app is manually distributed among `worker1`, `worker2`, and `worker3` behind Nginx.

### Cloud Run concept
In Cloud Run, you would normally deploy a single service. The platform handles instance creation and traffic routing for you. You would not manage `worker1`, `worker2`, and `worker3` yourself.

That means the important mental shift is:
- current repo: “I manually manage the worker pool”
- Cloud Run: “I provide a containerized service; the platform manages instances and traffic”

## 5. What is still not fully real yet

This repository is prepared for the learning and scaffolding part, but it is not yet a fully production-ready Cloud Run deployment because real cloud services are still missing.

The following would be needed for a real deployment:
- a real Google Cloud project,
- real credentials or service account access,
- a managed Postgres service such as Cloud SQL,
- a managed Redis service such as Memorystore or another shared Redis endpoint,
- secure environment variable or Secret Manager configuration,
- and deployment permissions for Cloud Run.

The current repo is therefore “cloud-prepared,” not “cloud-deployed.”

## 6. What the files are doing for you

Here is the practical file-by-file mapping:

- [app/Dockerfile](app/Dockerfile): makes the container compatible with Cloud Run-style port assignment.
- [app/core/config.py](app/core/config.py): centralizes runtime configuration and accepts environment-driven settings.
- [app/db/session.py](app/db/session.py): connects the app to database and Redis endpoints from environment variables.
- [app/.env.example](app/.env.example): shows the expected environment variable shape for local and cloud-style use.
- [docker-compose.yml](docker-compose.yml): keeps the manual distributed demo intact for learning and verification.
- [nginx.conf](nginx.conf): demonstrates the old manual load-balancer model.
- [cloudbuild.yaml](cloudbuild.yaml): shows the build-and-deploy shape for a Cloud Run pipeline.
- [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh): provides a deployment template for later use with real credentials.
- [.gcloudignore](.gcloudignore): trims the upload context for cloud builds.
- [README.md](README.md): explains the architectural shift and the repo’s purpose.
- [docs/cloud-run-prep.md](docs/cloud-run-prep.md): this document, which explains the rationale.

## 7. The key idea to remember

The repo is not being turned into a fully cloud-deployed system in this branch. Instead, it is being prepared so that you can clearly explain and understand the transition from:
- a manually managed, multi-container, Nginx-backed architecture,
to
- a managed service architecture where Cloud Run handles scaling and routing.

## 8. Interview-ready summary

If someone asked you, “How is this repo prepared for Google Cloud Run?”, you could answer:

> The repo now supports a Cloud Run-style runtime contract by honoring the platform-provided port, reading configuration from environment variables, and avoiding assumptions about a manually managed worker pool. The deployment artifacts for Cloud Build and Cloud Run are also included so the repository is structured for a managed deployment workflow. The remaining missing pieces for a real deployment are cloud credentials, a managed database, and a managed Redis service.

## 9. What you should focus on next

If you had real Google Cloud credentials, the deployment path would look like this.

### Step 1: Create or select a Google Cloud project
You would first create or select a Google Cloud project in the Google Cloud Console.

Why this matters:
- every Cloud Run deployment belongs to a project,
- IAM permissions and billing are scoped to that project,
- and the deployment artifacts in [cloudbuild.yaml](cloudbuild.yaml) and [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh) assume a target project.

What you would do:
- create a project,
- enable the Cloud Run API,
- enable Cloud Build API,
- and enable the APIs required for your database and cache services.

### Step 2: Set up authentication and credentials
You would need credentials to authenticate with the Google Cloud CLI and to let the build/deploy pipeline access your project.

Why this matters:
- without credentials, you cannot push images, deploy services, or manage cloud resources.
- this is the first hard requirement for real deployment.

What you would do:
- install the Google Cloud CLI,
- authenticate with `gcloud auth login`,
- set the active project with `gcloud config set project <PROJECT_ID>`,
- and, if needed, create a service account with deployment permissions.

### Step 3: Provision managed PostgreSQL
The current repository originally used a local master/replica PostgreSQL setup in [docker-compose.yml](docker-compose.yml). In Google Cloud, you would replace that local topology with a managed PostgreSQL service such as Cloud SQL.

Why this matters:
- the app needs a durable database,
- local containers are not a real production-grade storage solution,
- and Cloud Run instances should not depend on a database inside a container that can disappear on restart.

What you would do:
- create a Cloud SQL for PostgreSQL instance,
- create a database for the app,
- create a user with permissions,
- and collect the connection string.

Then you would feed that to the app through environment variables such as:
- `DATABASE_URL` for the main connection,
- `DATABASE_URL_READ` for the read path if you want separate read/write endpoints.

This is the Cloud-native equivalent of the local master/replica story in your current repo.

### Step 4: Provision managed Redis
The local version of this repo also uses a Redis container in [docker-compose.yml](docker-compose.yml). In Cloud Run, that should be replaced by a managed Redis service, such as Memorystore or any other accessible Redis endpoint.

Why this matters:
- the shared cache needs to survive instance recreation,
- and multiple Cloud Run instances need a common place to store cache values.

What you would do:
- create a Redis instance in Memorystore or use another managed Redis service,
- note its host, port, and authentication details,
- and set `REDIS_URL` in the Cloud Run service configuration.

### Step 5: Replace local-only placeholders with real environment values
The deployment script in [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh) and the example values in [cloudbuild.yaml](cloudbuild.yaml) currently contain placeholders.

Why this matters:
- the app cannot connect to real services without real environment values,
- and those values must be injected at deploy time.

What you would do:
- replace the placeholder database URIs with the actual Cloud SQL connection strings,
- replace the placeholder Redis URL with the actual managed Redis endpoint,
- and pass those values as secret or environment variables in the Cloud Run service definition.

### Step 6: Build and push the container image
The repository already includes [cloudbuild.yaml](cloudbuild.yaml), which describes a standard build flow:
- build the container,
- push it to Container Registry or Artifact Registry,
- and deploy it.

Why this matters:
- Cloud Run deploys from a container image,
- so the image must be built and stored in a registry that the platform can access.

What you would do:
- run the Cloud Build pipeline or manually build and push the image,
- confirm that the image is available in Artifact Registry,
- and proceed to deployment.

### Step 7: Deploy the service to Cloud Run
Once the image is available, you would deploy the service to Cloud Run.

Why this matters:
- this is the actual point where the container becomes a live service with auto-scaling and managed traffic routing.

What you would do:
- use the Cloud Run deploy command from [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh),
- set the runtime environment variables,
- specify the region,
- and enable or disable unauthenticated access depending on your needs.

### Step 8: Verify health and connectivity
After deployment, you would verify that the app is reachable and that the database/cache integration works.

Why this matters:
- deployment success is not just “the command returned successfully”;
- you must prove that the service can actually connect to its backing services.

What you would do:
- call the `/health` endpoint,
- check database connectivity,
- confirm Redis cache traffic is working,
- and inspect logs if the service fails to start.

### Step 9: Review what changes compared to the earlier local demo
This is the conceptual summary you should keep in mind.

In the old manual setup:
- you had explicit worker containers and an Nginx load balancer in [docker-compose.yml](docker-compose.yml),
- you managed the topology yourself,
- and you ran the database and cache locally.

In the Cloud Run setup:
- you deploy a single service,
- Cloud Run creates and scales instances for you,
- and you rely on managed services for Postgres and Redis.

That is the core architectural change.

## 10. The practical answer to your earlier questions

Yes, your list is basically correct.

1. You would need credentials.
2. You would need to configure managed PostgreSQL and Redis, replacing the local manual services from the earlier demo.
3. The later steps of building, deploying, and validating the service are the natural follow-up actions.

The main difference is that in the local repo, the infrastructure was visible and manual. In the cloud version, that infrastructure becomes managed by Google Cloud, while your application responsibilities shift to portability, configuration, and statelessness.
