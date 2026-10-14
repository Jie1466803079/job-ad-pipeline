#!/usr/bin/env bash
# The checks behind make demo: run daily-ingest in n8n for two companies, then check that the ingest
# stored rows, the review page answers, the digest email arrives and the webhook refuses strangers.
# make demo runs make env, make up and make n8n-setup first.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPANIES=${DEMO_COMPANIES:-Dovetail,Mable}
MAILPIT=http://127.0.0.1:8025

sql() { docker compose exec -T db psql -U jobpipe -d jobpipe -Atc "$1"; }
digest_count() {
  curl -s -G "$MAILPIT/api/v1/search" --data-urlencode 'query=subject:"Job digest"' \
    | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["messages_count"])'
}
fail() { echo "$1" >&2; exit 1; }

start=$(sql "SELECT now()")
digests_before=$(digest_count)
out=$(mktemp)
trap 'rm -f "$out"' EXIT

echo "1. Running daily-ingest in n8n for: $COMPANIES"
echo "   (with LLM_PROVIDER=gemini, each new ad can take up to two minutes)"
if ! docker compose run --rm --no-deps -T -e INGEST_COMPANIES="$COMPANIES" n8n \
    execute --id=wfDailyIngest001 > "$out" 2>&1; then
  grep -o '"message": *"[^"]*"' "$out" | head -3 >&2 || true
  fail "daily-ingest failed. The run is listed under Executions in n8n."
fi

echo "2. Checking the rows it stored"
rows=$(sql "SELECT c.name || ': ' || i.fetched || ' fetched, ' || i.created || ' new, ' || i.skipped
              || ' skipped, ' || i.tracked || ' tracked, ' || i.review || ' to review'
            FROM ingest_calls i JOIN companies c ON c.id = i.company_id
            WHERE i.started_at >= '$start' ORDER BY c.name")
echo "$rows" | sed 's/^/   /'
wanted=$(echo "$COMPANIES" | tr ',' '\n' | grep -c .)
[ "$(echo "$rows" | grep -c .)" -eq "$wanted" ] || fail "Expected one ingest row per company."
echo "   ads stored in total: $(sql "SELECT count(*) FROM postings")"

echo "3. Checking the review page"
curl -fsS http://127.0.0.1:8000/ | grep -q '<div id="root">' || fail "The review page did not load."
echo "   http://127.0.0.1:8000 answers"

echo "4. Sending the digest through n8n"
docker compose run --rm --no-deps -T n8n execute --id=wfDailyDigest001 > /dev/null 2>&1 \
  || fail "daily-digest failed. The run is listed under Executions in n8n."
for _ in $(seq 1 10); do
  [ "$(digest_count)" -gt "$digests_before" ] && break
  sleep 1
done
[ "$(digest_count)" -gt "$digests_before" ] || fail "No digest email arrived in Mailpit."
echo "   the digest is in Mailpit"

echo "5. Checking the job-link webhook"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:5678/webhook/job-link || true)
[ "$code" = 403 ] || fail "The webhook answered HTTP $code without the secret, not 403."
echo "   it refuses requests without the secret"

cat <<'EOF'

Demo finished. Everything runs on this machine:
  Review page  http://127.0.0.1:8000   make a login first: make user USERNAME=<name>
  n8n          http://127.0.0.1:5678   create the owner account on the first visit
  Mailpit      http://127.0.0.1:8025   the digest email
Send a job link (the secret is WEBHOOK_SECRET in .env):
  curl -X POST http://127.0.0.1:5678/webhook/job-link -H "X-Webhook-Secret: <secret>" \
    -H 'Content-Type: application/json' -d '{"url": "https://jobs.lever.co/<company>/<job id>"}'
EOF
