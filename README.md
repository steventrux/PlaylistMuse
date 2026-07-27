# PlaylistMuse

PlaylistMuse is a standalone, self-hosted web application that turns a natural-language prompt into a playlist and resolves the suggested tracks against the YouTube Music catalogue.

## Features

- Natural-language playlist requests
- Configurable track count from 5 to 100
- Filters for live recordings, covers and remixes
- AI providers: Google Gemini, OpenAI, Anthropic, Ollama and OpenAI-compatible endpoints
- YouTube Music catalogue resolution with fuzzy matching
- Responsive web interface
- Docker support

## Quick start with Docker

```bash
cp .env.example .env
# Add the provider, model and credentials to .env
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

## Configuration

The preferred method is through environment variables:

| Variable | Description |
| --- | --- |
| `PLAYLISTMUSE_AI_PROVIDER` | `gemini`, `openai`, `anthropic`, `ollama` or `custom` |
| `PLAYLISTMUSE_AI_API_KEY` | Provider API key; not required for a local Ollama server |
| `PLAYLISTMUSE_AI_MODEL` | Model identifier supported by the selected provider |
| `PLAYLISTMUSE_AI_BASE_URL` | Required for Ollama and custom endpoints |
| `PLAYLISTMUSE_DATA_DIR` | Persistent configuration directory; default `data` |

Settings can also be saved from the web interface. The generated `data/config.json` file is excluded from Git.

## API

- `GET /api/health`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/playlists/generate`

Interactive API documentation is available at `/docs`.

## Notes

PlaylistMuse resolves public YouTube Music catalogue results. It does not yet create or modify playlists inside a user's Google account.
