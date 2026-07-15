#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-your-project-id}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-issues-api}"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Placeholder deployment script for learning / interview preparation.
# Replace the environment values with real managed-service endpoints later.
echo "Building image for ${IMAGE}"

docker build -t "${IMAGE}" .
docker push "${IMAGE}"

gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=postgresql+psycopg2://..." \
  --set-env-vars "DATABASE_URL_READ=postgresql+psycopg2://..." \
  --set-env-vars "REDIS_URL=redis://..."
