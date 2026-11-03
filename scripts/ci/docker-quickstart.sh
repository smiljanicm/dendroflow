#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Accept an already-built image.
IMAGE="${1:-dendroflow:ci}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TEST_DIR="$(mktemp -d)"
TEST_ID="df-ci-$(basename "$TEST_DIR" | tr '[:upper:]' '[:lower:]')"
NETWORK="$TEST_ID"
POSTGRES="$TEST_ID-postgres"
SNAPSHOTS="$TEST_ID-snapshots"

cleanup() {
  local result=$?
  trap - EXIT

  if [ "$result" -ne 0 ]; then
    docker logs "$POSTGRES" >&2 || true
  fi

  docker rm -fv "$POSTGRES" >/dev/null 2>&1 || true
  docker volume rm "$SNAPSHOTS" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  rm -rf "$TEST_DIR"
  exit "$result"
}
trap cleanup EXIT

mkdir -p "$TEST_DIR/.demo"
cp examples/quickstart/logger.csv "$TEST_DIR/.demo/logger.csv"
cp examples/quickstart/config.yaml "$TEST_DIR/config.yaml"

docker network create "$NETWORK" >/dev/null
docker volume create "$SNAPSHOTS" >/dev/null

docker run --detach \
  --name "$POSTGRES" \
  --network "$NETWORK" \
  --network-alias postgres \
  -e POSTGRES_USER=dendroflow_test \
  -e POSTGRES_PASSWORD=ci-test-only \
  -e POSTGRES_DB=postgres \
  postgres:16 >/dev/null

# Wait for PostgreSQL, with a bounded timeout.
ready=false
for attempt in {1..60}; do
  if docker exec "$POSTGRES" \
      pg_isready -h 127.0.0.1 -U dendroflow_test -d postgres \
      >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done

if [ "$ready" != true ]; then
  echo "PostgreSQL did not become ready." >&2
  exit 1
fi

docker exec -i "$POSTGRES" \
  psql -U dendroflow_test -d postgres -v ON_ERROR_STOP=1 \
  < docker/postgres/init/01-create-databases.sql

# Mount only test inputs; application code comes from the image.
app() {
  docker run --rm -i \
    --network "$NETWORK" \
    --workdir /work \
    --mount "type=bind,source=$TEST_DIR,target=/work,readonly" \
    --mount "type=volume,source=$SNAPSHOTS,target=/snapshots" \
    -e POSTGRES_HOST=postgres \
    -e POSTGRES_PORT=5432 \
    -e POSTGRES_USER=dendroflow_test \
    -e POSTGRES_PASSWORD=ci-test-only \
    -e DENDROFLOW_ENVIRONMENT=local \
    -e DENDROFLOW_SNAPSHOT_DIR=/snapshots \
    "$IMAGE" "$@"
}

# Check all stored timestamps and values, including the total count.
check_values() {
  app python - "$1" <<'PY'
import sys
from datetime import datetime, timezone

from dendroflow.database import connect

count = int(sys.argv[1])
expected = [
    (datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc), 10.0),
    (datetime(2026, 1, 2, 0, 15, tzinfo=timezone.utc), 10.1),
    (datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc), 10.2),
][:count]

with connect("dendroflow_raw") as connection:
    actual = connection.execute(
        "SELECT timestamp, value FROM raw_observations ORDER BY timestamp"
    ).fetchall()

assert actual == expected, f"Expected {expected!r}, got {actual!r}"
print(f"Verified {count} observations.")
PY
}

# Capture original rows, including IDs and provenance.
original_rows() {
  docker exec "$POSTGRES" \
    psql -U dendroflow_test -d dendroflow_raw \
    -v ON_ERROR_STOP=1 -At \
    -c "SELECT row_to_json(r)
        FROM raw_observations AS r
        ORDER BY timestamp
        LIMIT 2"
}

app dendroflow migrate
app dendroflow config validate /work/config.yaml
app dendroflow config apply /work/config.yaml --yes

echo "First ingestion"
app dendroflow ingest --all --json
check_values 2
original_rows > "$TEST_DIR/original.json"

echo "Replay unchanged file"
app dendroflow ingest --all --json
check_values 2
original_rows > "$TEST_DIR/replayed.json"
diff -u "$TEST_DIR/original.json" "$TEST_DIR/replayed.json"

echo "Append one observation"
printf '%s\n' '2026-01-02 00:30:00,10.2' >> "$TEST_DIR/.demo/logger.csv"
app dendroflow ingest --all --json
check_values 3
original_rows > "$TEST_DIR/after-append.json"
diff -u "$TEST_DIR/original.json" "$TEST_DIR/after-append.json"

echo "Replay extended file"
app dendroflow ingest --all --json
check_values 3
original_rows > "$TEST_DIR/final.json"
diff -u "$TEST_DIR/original.json" "$TEST_DIR/final.json"

echo "Docker quickstart passed."
