#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="docker-compose.playlistmuse.yml"
CONTAINER="playlistmuse-test"
HEALTH_URL="http://127.0.0.1:5770/api/health"
ROOT_URL="http://127.0.0.1:5770/"
PLAYLIST_URL="http://127.0.0.1:5770/static/playlist.html"
PLAYLIST_CSS_URL="http://127.0.0.1:5770/static/playlist.css"
PLAYLIST_JS_URL="http://127.0.0.1:5770/static/playlist.js"
OPENAPI_URL="http://127.0.0.1:5770/openapi.json"
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
echo "Python compilation:"
docker exec "$CONTAINER" python -m compileall -q backend tests
echo "OK: backend and tests compiled"

echo
echo "Duplicate-track identity:"
docker exec "$CONTAINER" python -c "from backend.youtube import track_identity_key as k; assert k('Bé-Bop-A-Lula!', 'Gene Vincent') == k('be bop a lula', 'GENE VINCENT'); assert k('Woman', 'Wolfmother') == k('Woman', 'Wolfmother')"
echo "OK: alternate uploads share one track identity"

echo
echo "Provider credential separation:"
docker exec "$CONTAINER" python -c "from backend.config import AppConfig, api_key_matches_provider, api_key_slot; assert api_key_slot('openrouter_auto') == 'openrouter'; assert api_key_slot('openrouter_free') == 'openrouter'; c=AppConfig(provider_api_keys={'openrouter':'sk-or-saved'}); assert c.key_is_saved('openrouter_auto') and c.key_is_saved('openrouter_free'); assert not api_key_matches_provider('gemini','sk-or-v1-wrong'); assert not AppConfig(provider='gemini',api_key='sk-or-v1-wrong',model='gemini-3.6-flash').configured"
echo "OK: provider keys are shared only where intended"

echo
echo "Gemini request safety:"
grep -Fq 'x-goog-api-key' backend/llm.py
grep -Fq 'responseFormat' backend/llm.py
if grep -Fq 'params={"key"' backend/llm.py; then
  echo "ERROR: Gemini API key is still sent in the URL query string" >&2
  exit 1
fi
echo "OK: Gemini key uses a header and structured response format"

echo
echo "AI generation strategy:"
docker exec "$CONTAINER" python -c "from backend.llm import _attempt_count, _playlist_response_format; full=_playlist_response_format(25, exact_count=True)['json_schema']['schema']['properties']['tracks']; batch=_playlist_response_format(6)['json_schema']['schema']['properties']['tracks']; assert full['minItems']==25 and full['maxItems']==25; assert batch['minItems']==1 and batch['maxItems']==6; assert _attempt_count('openrouter_free')==2"
grep -Fq 'response-healing' backend/llm.py
grep -Fq '_try_complete_request' backend/llm.py
grep -Fq '_complete_in_batches' backend/llm.py
grep -Fq '_replenishment_prompt' backend/main.py
echo "OK: complete request first, AI batching and YouTube replenishment enabled"

echo
echo "Health endpoint:"
curl --fail --silent --show-error "$HEALTH_URL"
echo

echo
echo "Settings endpoint:"
settings_json="$(curl --fail --silent --show-error "$SETTINGS_URL")"
echo "$settings_json"
for required_key in provider model fallback_1 fallback_2 base_url configured api_key_set provider_keys_set; do
  if ! grep -Fq "\"${required_key}\":" <<<"$settings_json"; then
    echo "ERROR: settings response is missing key: $required_key" >&2
    exit 1
  fi
done
echo "OK: settings schema"

echo
echo "Frontend structure:"
frontend_html="$(curl --fail --silent --show-error "$ROOT_URL")"
for required_text in "From Prompt" "From Seed" "AI provider" "Fallbacks" "OpenRouter Auto" "OpenRouter Free" "YouTube Music account"; do
  if ! grep -Fq "$required_text" <<<"$frontend_html"; then
    echo "ERROR: frontend is missing: $required_text" >&2
    exit 1
  fi
  echo "OK: $required_text"
done

echo
echo "Playlist result structure:"
playlist_html="$(curl --fail --silent --show-error "$PLAYLIST_URL")"
for required_id in playlist-name playlist-summary playlist-description track-list; do
  if ! grep -Fq "id=\"${required_id}\"" <<<"$playlist_html"; then
    echo "ERROR: playlist page is missing: $required_id" >&2
    exit 1
  fi
  echo "OK: $required_id"
done

playlist_js="$(curl --fail --silent --show-error "$PLAYLIST_JS_URL")"
for required_text in "track-details" "Open in YouTube Music" "Replace track" "/api/playlists/replace-track"; do
  if ! grep -Fq "$required_text" <<<"$playlist_js"; then
    echo "ERROR: playlist script is missing: $required_text" >&2
    exit 1
  fi
  echo "OK: $required_text"
done

openapi_json="$(curl --fail --silent --show-error "$OPENAPI_URL")"
if ! grep -Fq '"/api/playlists/replace-track"' <<<"$openapi_json"; then
  echo "ERROR: replacement API endpoint is missing" >&2
  exit 1
fi
echo "OK: replacement API"

curl --fail --silent --show-error --output /dev/null "$PLAYLIST_CSS_URL"
echo "OK: playlist.css"

echo
echo "Frontend HTTP status:"
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' "$ROOT_URL"

echo
echo "Playlist page HTTP status:"
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' "$PLAYLIST_URL"

echo
echo "Recent logs:"
docker logs --tail 50 "$CONTAINER"

echo
echo "PlaylistMuse VPS smoke test passed."
