#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="docker-compose.playlistmuse.yml"
CONTAINER="playlistmuse-test"
HEALTH_URL="http://127.0.0.1:5770/api/health"
ROOT_URL="http://127.0.0.1:5770/"
SETTINGS_URL="http://127.0.0.1:5770/api/settings"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not in PATH." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose v2 is not available." >&2
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: $COMPOSE_FILE not found in $(pwd)." >&2
  exit 1
fi

if ! docker volume inspect playlistmuse-data >/dev/null 2>&1; then
  echo "Creating external volume playlistmuse-data..."
  docker volume create playlistmuse-data >/dev/null
fi

echo "Stopping the previous test deployment..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans

echo "Building and starting PlaylistMuse..."
docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate

echo "Waiting for the container healthcheck..."
for attempt in $(seq 1 30); do
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || true)"
  printf 'Attempt %02d/30: %s\n' "$attempt" "${status:-not-created}"
  if [[ "$status" == "healthy" ]]; then
    break
  fi
  if [[ "$status" == "exited" || "$status" == "dead" ]]; then
    echo "ERROR: container stopped unexpectedly." >&2
    docker logs --tail 200 "$CONTAINER" || true
    exit 1
  fi
  sleep 3
done

status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || true)"
if [[ "$status" != "healthy" ]]; then
  echo "ERROR: container did not become healthy." >&2
  docker compose -f "$COMPOSE_FILE" ps
  docker logs --tail 200 "$CONTAINER" || true
  exit 1
fi

echo
echo "Container status:"
docker compose -f "$COMPOSE_FILE" ps

echo
echo "Health endpoint:"
curl --fail --silent --show-error "$HEALTH_URL"
echo

echo
echo "Settings endpoint:"
curl --fail --silent --show-error "$SETTINGS_URL"
echo

echo
echo "Frontend HTTP status:"
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' "$ROOT_URL"

echo
echo "Recent logs:"
docker logs --tail 50 "$CONTAINER"

echo
echo "PlaylistMuse VPS smoke test passed."
