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

If you had real Google Cloud credentials, the next steps would be:
1. replace the placeholder URLs in [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh) with actual service endpoints,
2. configure Cloud SQL / Redis endpoints and credentials,
3. run the Cloud Build pipeline from [cloudbuild.yaml](cloudbuild.yaml),
4. deploy the service with Cloud Run,
5. verify health and connectivity from the live environment.
