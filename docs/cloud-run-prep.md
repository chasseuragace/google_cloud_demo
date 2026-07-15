# Cloud Run preparation notes

This branch is not meant to deploy to Google Cloud yet. It is meant to show the architectural shift from a manual local stack to a platform-managed deployment model.

## What changes conceptually?

### Current repo shape
- Nginx sits in front of three worker containers.
- The compose file explicitly defines each worker and its dependencies.
- Load distribution is manual and visible in the topology.

### Cloud Run shape
- The application is deployed as a single service.
- Cloud Run creates and scales instances automatically.
- Traffic is distributed by Google’s managed front-end.
- You do not manage worker names such as `worker1` / `worker2` / `worker3` yourself.

## Why this matters

Cloud Run expects the app to be stateless and to read configuration from environment variables. That means:
- no reliance on in-memory state for critical business behavior,
- explicit use of shared services such as Cloud SQL and Redis,
- and runtime compatibility with the platform’s `PORT` contract.

## What remains local for now

- Docker Compose is still useful for local development and demonstrations.
- The repo can still run its test suite and local experiments.
- The deployment artifacts are present as templates and documentation for future use.
