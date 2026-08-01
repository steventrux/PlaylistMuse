<div align="center">
  <img src=".github/assets/playlistmuse-hero.svg" alt="PlaylistMuse — AI-assisted playlist creation for YouTube Music" width="100%">

  <br><br>

  <a href="https://github.com/steventrux/PlaylistMuse/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://img.shields.io/github/actions/workflow/status/steventrux/PlaylistMuse/ci.yml?branch=main&style=flat-square&label=CI&logo=github" alt="CI status"></a>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-0.116+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker ready">
  <img src="https://img.shields.io/badge/self--hosted-yes-8B5CF6?style=flat-square" alt="Self-hosted">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/steventrux/PlaylistMuse?style=flat-square&color=EC4899" alt="MIT license"></a>

  <p>
    Turn a natural-language idea or a seed song into an editable YouTube Music playlist.<br>
    Refine the result, replace individual tracks and publish it directly from the browser.
  </p>

  <p>
    <a href="#features"><strong>Features</strong></a> ·
    <a href="#how-it-works"><strong>How it works</strong></a> ·
    <a href="#quick-start"><strong>Quick start</strong></a> ·
    <a href="#ai-providers"><strong>AI providers</strong></a> ·
    <a href="#youtube-music-publishing"><strong>YouTube Music</strong></a>
  </p>
</div>

---

## What is PlaylistMuse?

PlaylistMuse is a self-hosted web application that turns a written idea or a reference song into a complete YouTube Music playlist.

Describe a mood, genre, era, activity or sound, or start from an existing track. PlaylistMuse asks the selected AI provider for suitable songs, resolves every suggestion against the YouTube Music catalogue and removes unwanted duplicates, live recordings, covers or remixes according to your preferences.

The result remains editable before publication. Review track details, replace individual songs, change the title, choose playlist visibility and publish the final sequence directly to YouTube Music.

## Features

| Create | Refine | Publish |
| --- | --- | --- |
| Natural-language prompts | Expandable track details | Direct YouTube Music publishing |
| Seed-song generation | Individual track replacement | Private, unlisted or public playlists |
| 5–100 requested tracks | Live, cover and remix filters | Google OAuth device authorization |
| Multiple AI providers | Duplicate prevention and replenishment | Locally generated cover mosaic |

Additional highlights:

- Google Gemini, OpenAI, Anthropic, OpenRouter, Ollama and OpenAI-compatible endpoints
- Automatic model discovery based on the configured provider
- Multiple AI provider profiles with quick switching
- OpenRouter Auto and Free routing modes
- Fuzzy catalogue matching against real YouTube Music tracks
- Four-tile playlist artwork generated locally in the browser
- Responsive interface built with semantic HTML, modern CSS and vanilla JavaScript
- Docker-based deployment with persistent application data

## How it works

1. **Start with an idea or a song.**  
   Write a prompt or select a YouTube Music track as the musical reference.

2. **Generate and resolve the playlist.**  
   The active AI provider proposes songs, then PlaylistMuse matches them to real catalogue entries with title, artist, album, duration and artwork.

3. **Clean and refine the result.**  
   Duplicates and excluded versions are removed, missing positions are replenished and individual tracks can be replaced without regenerating the whole playlist.

4. **Publish to YouTube Music.**  
   Edit the title, choose the visibility and create the playlist in the connected account.

## Quick start

### Requirements

- Docker Engine
- Docker Compose v2

### Run with Docker Compose

```bash
git clone https://github.com/steventrux/PlaylistMuse.git
cd PlaylistMuse
cp .env.example .env
docker compose up -d --build
```

Open **http://localhost:5780**.

On first launch, the onboarding flow guides you through configuring the AI provider and YouTube Music.

Application settings, provider credentials and YouTube authorization data are stored in the persistent `./data` directory.

To stop PlaylistMuse:

```bash
docker compose down
```

## AI providers

| Provider | Model selection | Notes |
| --- | --- | --- |
| Google Gemini | Models available to the configured API key | Availability can depend on the Google project |
| OpenAI | Compatible models available to the account | Non-chat models are excluded |
| Anthropic | Claude models available to the account | Availability follows account access |
| OpenRouter Auto | `openrouter/auto` | OpenRouter selects the model automatically |
| OpenRouter Free | `openrouter/free` | Uses OpenRouter's free routing pool |
| Ollama | Models installed on the configured server | Embedding-only models are excluded |
| Compatible endpoint | Models reported by an OpenAI-compatible `/models` endpoint | Manual model identifiers are supported |

Provider credentials and model settings are managed from the web interface. Configured providers can be switched without editing application files.

## YouTube Music publishing

Connecting YouTube Music is optional. Playlist generation, editing and track replacement work without it.

To enable direct publishing:

1. Create or select a project in Google Cloud Console.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen.
4. Create an OAuth client of type **TVs and Limited Input devices**.
5. Open **YouTube Music Settings** in PlaylistMuse.
6. Save the OAuth client ID and secret.
7. Select **Connect account** and complete Google's device authorization flow.

After connection, PlaylistMuse can create **Private**, **Unlisted** or **Public** playlists directly in the connected YouTube Music account.

OAuth credentials and the refreshable account token are stored in the persistent data directory with restricted file permissions. Saved secrets are never returned to the browser.

## Self-hosting

PlaylistMuse is designed for personal self-hosting on a server, NAS or VPS.

Recommended practices:

- Keep access limited to the local network, a VPN or another trusted private network.
- For remote access, use a reverse proxy with HTTPS and an authentication layer.
- Back up the persistent `data` directory.
- Never commit provider keys, OAuth credentials, tokens or application data.
- Keep the container and dependencies updated.

The container listens on port `5780` and exposes `GET /api/health` for health monitoring.

## Technology

- **Backend:** Python 3.12, FastAPI, Uvicorn and HTTPX
- **AI integration:** provider-specific REST APIs and OpenAI-compatible endpoints
- **Music catalogue:** `ytmusicapi`
- **Frontend:** semantic HTML, modern CSS and vanilla JavaScript
- **Deployment:** Docker and Docker Compose
- **Quality:** Pytest, Ruff and Node's built-in test runner

<details>
<summary><strong>Development and testing</strong></summary>

### Local backend

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
uvicorn backend.main:app --reload --port 5780
```

### Test suite

```bash
python -m compileall -q backend tests
ruff check --select E4,E7,E9,F backend tests
python -m pytest -q

find frontend -maxdepth 1 -name "*.js" -print0 | xargs -0 -n1 node --check
find tests -maxdepth 1 -name "*.cjs" -print0 | xargs -0 -n1 node --check
node --test tests/*.cjs
```

</details>

## Contributing

Issues and pull requests are welcome. Keep changes focused, preserve the self-hosted architecture and include regression tests for behavior changes.

## Disclaimer

PlaylistMuse is an independent project and is not affiliated with Google or YouTube.

`ytmusicapi` is an unofficial YouTube Music client. Google or YouTube may change authentication requirements or internal endpoints without notice.

## License

PlaylistMuse is released under the [MIT License](LICENSE).

<div align="center">
  <sub>Built for people who would rather describe a sound than manually assemble a queue.</sub>
</div>
