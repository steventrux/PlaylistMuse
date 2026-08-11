#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="${PLAYLISTMUSE_SMOKE_COMPOSE_FILE:-docker-compose.yml}"
CONTAINER="${PLAYLISTMUSE_SMOKE_CONTAINER:-playlistmuse}"
BASE_URL="${PLAYLISTMUSE_SMOKE_URL:-http://127.0.0.1:5780}"
EXPECTED_APP_VERSION="${PLAYLISTMUSE_EXPECTED_APP_VERSION:-0.2.0}"
EXPECTED_BUILD_CHANNEL="${PLAYLISTMUSE_EXPECTED_BUILD_CHANNEL:-dev}"

HEALTH_URL="$BASE_URL/api/health"
VERSION_URL="$BASE_URL/api/version"
ROOT_URL="$BASE_URL/"
LIBRARY_URL="$BASE_URL/static/library.html"
PLAYLIST_URL="$BASE_URL/static/playlist.html"
OPENAPI_URL="$BASE_URL/openapi.json"
SETTINGS_URL="$BASE_URL/api/settings"
YOUTUBE_STATUS_URL="$BASE_URL/api/youtube/status"
YOUTUBE_SETTINGS_URL="$BASE_URL/api/youtube/settings"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_text() {
  local haystack="$1"
  local needle="$2"
  local label="${3:-$2}"
  grep -Fq "$needle" <<<"$haystack" || fail "missing $label"
  echo "OK: $label"
}

fetch() {
  curl --fail --silent --show-error "$1"
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not in PATH"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is not available"
[[ -f "$COMPOSE_FILE" ]] || fail "$COMPOSE_FILE not found in $(pwd)"
[[ -f .env ]] || fail ".env not found in $(pwd)"

echo "Stopping previous dev deployment..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans

echo "Building and starting PlaylistMuse..."
docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate

echo "Waiting for application health..."
ready=0
for attempt in $(seq 1 30); do
  container_state="$(docker inspect --format '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
  printf 'Attempt %02d/30: container=%s\n' "$attempt" "${container_state:-not-created}"

  if [[ "$container_state" == "exited" || "$container_state" == "dead" ]]; then
    docker logs --tail 200 "$CONTAINER" || true
    fail "container stopped unexpectedly"
  fi

  if curl --fail --silent "$HEALTH_URL" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if [[ "$ready" != "1" ]]; then
  docker compose -f "$COMPOSE_FILE" ps
  docker logs --tail 200 "$CONTAINER" || true
  fail "application health endpoint did not become ready"
fi

echo
echo "Container status:"
docker compose -f "$COMPOSE_FILE" ps

echo
echo "Backend compilation:"
docker exec "$CONTAINER" python -m compileall -q backend
echo "OK: backend compiled"

echo
echo "Core backend invariants:"
docker exec -i "$CONTAINER" python - <<'PY'
from backend.youtube import track_identity_key as key
from backend.config import AppConfig, api_key_matches_provider, api_key_slot
from backend.youtube_routes import YouTubePlaylistCreateRequest

assert key("Bé-Bop-A-Lula!", "Gene Vincent") == key("be bop a lula", "GENE VINCENT")
assert api_key_slot("openrouter_auto") == "openrouter"
assert api_key_slot("openrouter_free") == "openrouter"
config = AppConfig(provider_api_keys={"openrouter": "sk-or-saved"})
assert config.key_is_saved("openrouter_auto") and config.key_is_saved("openrouter_free")
assert not api_key_matches_provider("gemini", "sk-or-v1-wrong")
request = YouTubePlaylistCreateRequest(
    title="Test",
    privacy_status="UNLISTED",
    video_ids=["b", "a", "b"],
)
assert request.video_ids == ["b", "a"]
assert request.privacy_status == "UNLISTED"
PY
docker exec "$CONTAINER" python -c "from backend.version import APP_VERSION; assert APP_VERSION == '$EXPECTED_APP_VERSION', APP_VERSION"
echo "OK: version, track identity, provider separation and YouTube request normalization"

echo
echo "Health and version metadata:"
health_json="$(fetch "$HEALTH_URL")"
version_json="$(fetch "$VERSION_URL")"
openapi_json="$(fetch "$OPENAPI_URL")"
python - "$EXPECTED_APP_VERSION" "$EXPECTED_BUILD_CHANNEL" "$health_json" "$version_json" "$openapi_json" <<'PY'
import json
import sys

expected_version, expected_channel, health_raw, version_raw, openapi_raw = sys.argv[1:]
health = json.loads(health_raw)
version = json.loads(version_raw)
openapi = json.loads(openapi_raw)

assert health["status"] == "healthy", health
assert health["application"] == "PlaylistMuse", health
assert openapi["info"]["version"] == expected_version, openapi["info"]
assert version["channel"] == expected_channel, version
if expected_channel == "stable":
    assert version["version"] == expected_version, version
else:
    assert version["version"] == "dev", version
print(version)
PY
echo "OK: application version $EXPECTED_APP_VERSION and build channel $EXPECTED_BUILD_CHANNEL"

echo
echo "Settings and YouTube API schemas:"
settings_json="$(fetch "$SETTINGS_URL")"
youtube_settings_json="$(fetch "$YOUTUBE_SETTINGS_URL")"
youtube_status_json="$(fetch "$YOUTUBE_STATUS_URL")"
for required_key in provider model fallback_1 fallback_2 base_url configured api_key_set provider_keys_set; do
  require_text "$settings_json" "\"${required_key}\":" "settings.$required_key"
done
for required_key in client_id client_secret_set configured; do
  require_text "$youtube_settings_json" "\"${required_key}\":" "youtube-settings.$required_key"
done
if grep -Fq 'client_secret"' <<<"$youtube_settings_json"; then
  fail "YouTube client secret was exposed by the settings endpoint"
fi
for required_key in catalog_available credentials_configured account_connected message; do
  require_text "$youtube_status_json" "\"${required_key}\":" "youtube-status.$required_key"
done

echo
echo "Home page:"
home_html="$(fetch "$ROOT_URL")"
for required_text in "From Prompt" "From Seed" "AI provider" "Fallbacks" "OpenRouter Auto" "OpenRouter Free" "YouTube Music account"; do
  require_text "$home_html" "$required_text"
done

echo
echo "Playlist editor page:"
playlist_html="$(fetch "$PLAYLIST_URL")"
for required_id in playlist-name playlist-summary playlist-description playlist-tags youtube-publish-warning youtube-publish-controls create-youtube-playlist playlist-draft-actions add-track refine-playlist playlist-add-track-host playlist-refine-host track-list; do
  require_text "$playlist_html" "id=\"${required_id}\"" "$required_id"
done
for privacy_value in PRIVATE UNLISTED PUBLIC; do
  require_text "$playlist_html" "data-privacy=\"${privacy_value}\"" "privacy $privacy_value"
done
for required_asset in \
  "/static/common.js?v=1" \
  "/static/playlist-save-status.js?v=2" \
  "/static/playlist-mosaic.js?v=1" \
  "/static/library-tags.js?v=3" \
  "/static/playlist.js?v=20" \
  "/static/playlist-add-track.js?v=2" \
  "/static/playlist-refine.js?v=2" \
  "/static/youtube-publish.js?v=15"; do
  require_text "$playlist_html" "$required_asset" "$required_asset"
done

echo
echo "Playlist editor JavaScript and autosave:"
playlist_js="$(fetch "$BASE_URL/static/playlist.js")"
add_track_js="$(fetch "$BASE_URL/static/playlist-add-track.js")"
refine_js="$(fetch "$BASE_URL/static/playlist-refine.js")"
save_status_js="$(fetch "$BASE_URL/static/playlist-save-status.js")"
playlist_header_css="$(fetch "$BASE_URL/static/playlist-header.css")"
for required_text in "Open in YouTube Music" "Replace track" "/api/playlists/replace-track"; do
  require_text "$playlist_js" "$required_text"
done
require_text "$add_track_js" "/api/seeds/search" "add-track search"
require_text "$add_track_js" "manual_add" "manual add history"
require_text "$add_track_js" "manual_remove" "manual remove history"
require_text "$refine_js" "/refine-preview" "refinement preview"
require_text "$refine_js" "/refine-apply" "refinement apply"
require_text "$refine_js" "Removed" "refinement removed summary"
require_text "$refine_js" "Added" "refinement added summary"
for required_text in "Saving…" "Saved" "Save failed"; do
  require_text "$save_status_js" "$required_text" "autosave: $required_text"
done
require_text "$playlist_header_css" ".playlist-save-status" "autosave CSS"
require_text "$playlist_header_css" "position: fixed" "autosave fixed viewport position"
require_text "$playlist_header_css" "bottom: 18px" "autosave desktop bottom position"

echo
echo "Library page:"
library_html="$(fetch "$LIBRARY_URL")"
library_js="$(fetch "$BASE_URL/static/library.js")"
for required_id in library-search library-count library-list library-empty library-pagination; do
  require_text "$library_html" "id=\"${required_id}\"" "$required_id"
done
require_text "$library_html" "/static/library.js?v=11" "current library script"
require_text "$library_js" "item.status === 'draft' ? 'Edit' : 'Open'" "Draft=Edit / Published=Open"
require_text "$library_js" "Refinements" "refinement history"

echo
echo "Published read-only and atomic publication guards:"
application_py="$(docker exec "$CONTAINER" cat backend/application.py)"
youtube_publish_py="$(docker exec "$CONTAINER" cat backend/youtube_publish.py)"
require_text "$application_py" "Published playlists are read-only" "published API read-only guard"
require_text "$youtube_publish_py" "_rollback_playlist" "YouTube publication rollback path"
require_text "$youtube_publish_py" "YouTube rejected" "YouTube rejected-track failure path"

echo
echo "OpenAPI routes:"
for required_route in \
  "/api/playlists/replace-track" \
  "/api/library/playlists" \
  "/api/library/playlists/{playlist_id}/refine-preview" \
  "/api/library/playlists/{playlist_id}/refine-apply" \
  "/api/youtube/settings" \
  "/api/youtube/status" \
  "/api/youtube/connect/start" \
  "/api/youtube/connect/poll" \
  "/api/youtube/connection" \
  "/api/youtube/playlists"; do
  require_text "$openapi_json" "\"${required_route}\"" "$required_route"
done

echo
echo "Static asset HTTP checks:"
for asset in \
  style.css layout.css controls.css playlist.css playlist-editor.css playlist-refine.css \
  playlist-header.css compact-cards.css library-tags.css youtube.css youtube-results.css \
  common.js playlist-save-status.js playlist-mosaic.js playlist.js playlist-add-track.js \
  playlist-refine.js library.js youtube-account.js youtube-publish.js; do
  curl --fail --silent --show-error --output /dev/null "$BASE_URL/static/$asset"
done
echo "OK: current frontend assets"

echo
echo "Recent logs:"
docker logs --tail 50 "$CONTAINER"

echo
echo "PlaylistMuse 0.2.0 VPS smoke test passed."
