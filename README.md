# PlaylistMuse

PlaylistMuse is a standalone, self-hosted web application that turns a natural-language prompt or a seed song into an editable YouTube Music playlist.

## Features

- Natural-language playlist requests and seed-song generation
- Configurable track count from 5 to 100
- Filters for live recordings, covers and remixes
- AI providers: Google Gemini, OpenAI, Anthropic, OpenRouter Auto, OpenRouter Free, Ollama and OpenAI-compatible endpoints
- YouTube Music catalogue resolution with fuzzy matching and automatic replenishment
- Expandable track details and AI-assisted track replacement
- Google OAuth device authorization for a YouTube Music account
- Direct playlist creation with private, unlisted or public visibility
- Responsive web interface
- Docker support

## Quick start with Docker

```bash
cp .env.example .env
# Add the provider, model and credentials to .env, or configure them in the web UI
docker compose up -d --build
```

Open `http://localhost:5766`.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 5766
```

## AI configuration

The preferred method is the Settings panel. Environment variables can also be used:

| Variable | Description |
| --- | --- |
| `PLAYLISTMUSE_AI_PROVIDER` | `gemini`, `openai`, `anthropic`, `openrouter_auto`, `openrouter_free`, `ollama` or `custom` |
| `PLAYLISTMUSE_AI_API_KEY` | Provider API key; not required for a local Ollama server |
| `PLAYLISTMUSE_AI_MODEL` | Model identifier supported by the selected provider |
| `PLAYLISTMUSE_AI_FALLBACK_1` | Optional first fallback model |
| `PLAYLISTMUSE_AI_FALLBACK_2` | Optional second fallback model |
| `PLAYLISTMUSE_AI_BASE_URL` | Required for Ollama and custom endpoints |
| `PLAYLISTMUSE_DATA_DIR` | Persistent configuration directory; default `data` |

AI settings are stored in `data/config.json`, which is excluded from Git.

## MusicBrainz metadata and exclusion validation

MusicBrainz shadow collection is an opt-in diagnostic mode. It runs after playlist generation, does not change playlist tracks or API responses, and has no controls in the web interface.

An additional experimental active filter can validate already resolved YouTube Music tracks before they are returned. It is disabled by default. When enabled, MusicBrainz is queried neutrally and the three existing structured playlist selectors are applied afterwards. Tracks with explicit evidence for a selected live, cover or remix exclusion are removed and the normal replenishment loop requests replacements. Missing or temporarily unavailable MusicBrainz data fails open and does not break playlist creation.

| Variable | Description |
| --- | --- |
| `PLAYLISTMUSE_MUSICBRAINZ_SHADOW` | Set to `true` to enable background metadata collection; default `false` |
| `PLAYLISTMUSE_MUSICBRAINZ_SHADOW_SAMPLE` | Number of final tracks sampled per playlist, from 1 to 10; default `5` |
| `PLAYLISTMUSE_MUSICBRAINZ_CONTACT` | Optional contact URL or email included in the MusicBrainz User-Agent |
| `PLAYLISTMUSE_MUSICBRAINZ_SHADOW_PATH` | Optional NDJSON output path; default `data/musicbrainz-shadow.ndjson` |
| `PLAYLISTMUSE_MUSICBRAINZ_ACTIVE_FILTER` | Set to `true` to enable synchronous exclusion validation; default `false` |
| `PLAYLISTMUSE_MUSICBRAINZ_ACTIVE_PATH` | Optional NDJSON output path; default `data/musicbrainz-active.ndjson` |

The collectors record candidate MBIDs, artist MBIDs, ISRCs, release metadata, tags, relationship evidence, retry attempts and exclusion decisions. Requests are serialized to respect MusicBrainz rate limits. NDJSON files are private application data, are created with restricted file permissions where supported and are excluded from Git.

## Connect YouTube Music

PlaylistMuse uses the Google OAuth device authorization flow supported by `ytmusicapi`.

1. Create or select a project in Google Cloud Console.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen for the Google account that will use PlaylistMuse.
4. Create an OAuth client ID with application type **TVs and Limited Input devices**.
5. Open PlaylistMuse Settings and enter the Google OAuth client ID and client secret.
6. Select **Save Google credentials**, then **Connect account**.
7. Complete the authorization on the Google page using the displayed code.

The OAuth client configuration and refreshable account token are stored in the persistent data directory with file permissions restricted to the application user. They are never returned to the browser after being saved.

When an account is connected, the results page allows the edited playlist title, AI-generated description and current track order to be sent directly to YouTube Music. Visibility can be set to **Private**, **Unlisted** or **Public**.

## API

- `GET /api/health`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/playlists/generate`
- `POST /api/playlists/generate-from-seed`
- `POST /api/playlists/replace-track`
- `GET /api/youtube/settings`
- `PUT /api/youtube/settings`
- `GET /api/youtube/status`
- `POST /api/youtube/connect/start`
- `POST /api/youtube/connect/poll`
- `DELETE /api/youtube/connection`
- `POST /api/youtube/playlists`

Interactive API documentation is available at `/docs`.

## Security notes

PlaylistMuse is designed for self-hosting. Keep the persistent data volume private, expose the application through HTTPS, restrict access to trusted users and never commit OAuth credentials or tokens to Git.

`ytmusicapi` is an unofficial YouTube Music client. YouTube or Google may change authentication or internal endpoints without notice.
