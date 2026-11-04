#!/usr/bin/env bash
# Load n8n's credentials and workflows into the running stack, then publish the workflows.
# Safe to run again, for example after editing a workflow or changing a secret in .env.
# Usage: make n8n-setup   (which runs make up first)
set -euo pipefail
cd "$(dirname "$0")/.."

# The error workflow first, so it is live before any workflow that reports to it.
WORKFLOW_IDS=(wfErrorAlert0001 wfDailyIngest001 wfSubmitLink0001 wfDailyDigest001 wfMaintenance001)
WEBHOOK=http://127.0.0.1:5678/webhook/job-link

echo "Importing credentials from .env"
docker compose exec -T api python -m jobpipe.n8n_credentials \
  | docker compose exec -T n8n n8n import:credentials --input=/dev/stdin

echo "Importing workflows from n8n/workflows"
docker compose exec -T n8n n8n import:workflow --separate --input=/opt/n8n-import/workflows

# An import unpublishes every workflow it touches. n8n picks up a publish within about 15 seconds;
# the CLI's note that n8n must be restarted is out of date.
echo "Publishing workflows"
for id in "${WORKFLOW_IDS[@]}"; do
  docker compose exec -T n8n n8n publish:workflow --id="$id" > /dev/null
done

echo "Waiting for the job-link webhook"
code=000
for _ in $(seq 1 60); do
  # Without the secret, a live webhook answers 403; one that is not published yet answers 404.
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$WEBHOOK" || true)
  if [ "$code" = 403 ]; then
    echo "n8n is ready: ${#WORKFLOW_IDS[@]} workflows published."
    exit 0
  fi
  sleep 1
done
echo "The job-link webhook was not live after 60 seconds (last answer: HTTP $code)." >&2
exit 1
