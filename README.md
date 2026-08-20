<div align="center">
  <img alt="PlaylistMuse" src="frontend/playlistmuse-banner.svg" width="100%">

  <p>
    <strong>Describe the playlist you want. Get real tracks, ready to refine and publish.</strong>
  </p>

  <br>

  <a href="https://github.com/steventrux/PlaylistMuse/releases/latest"><img src="https://img.shields.io/github/v/release/steventrux/PlaylistMuse?style=flat-square&label=release" alt="Latest release" height="24"></a>
  <a href="https://github.com/steventrux/PlaylistMuse/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://img.shields.io/github/actions/workflow/status/steventrux/PlaylistMuse/ci.yml?branch=main&style=flat-square&label=CI&logo=github" alt="CI status" height="24"></a>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" height="24">
  <img src="https://img.shields.io/badge/FastAPI-0.116+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" height="24">
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker ready" height="24">
  <img src="https://img.shields.io/badge/self--hosted-yes-8B5CF6?style=flat-square" alt="Self-hosted" height="24">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/steventrux/PlaylistMuse?style=flat-square&color=EC4899" alt="MIT license" height="24"></a>
  <img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fstats.playlistmuse.workers.dev%2Fbadge.json&style=flat-square" alt="Playlists generated across all opted-in installations" height="24">

  <p>
    Create, refine, save and publish YouTube Music playlists from a written idea or a reference song, running entirely on your own server.
  </p>

  <p>
    <a href="#why-playlistmuse"><strong>Why PlaylistMuse</strong></a>
    &nbsp;·&nbsp;
    <a href="#screenshots"><strong>Screenshots</strong></a>
    &nbsp;·&nbsp;
    <a href="#features"><strong>Features</strong></a>
    &nbsp;·&nbsp;
    <a href="#quick-start"><strong>Quick start</strong></a>
    &nbsp;·&nbsp;
    <a href="#installation"><strong>Installation</strong></a>
    &nbsp;·&nbsp;
    <a href="#configuration"><strong>Configuration</strong></a>
    &nbsp;·&nbsp;
    <a href="#data-backup-and-updates"><strong>Data, backup & updates</strong></a>
    &nbsp;·&nbsp;
    <a href="#roadmap"><strong>Roadmap</strong></a>
    &nbsp;·&nbsp;
    <a href="#support-and-feedback"><strong>Support & feedback</strong></a>
  </p>
</div>

<br>

## Overview

PlaylistMuse turns a written idea into a finished playlist. Describe the sound, mood, era, activity or musical direction you want, or hand it a reference track to build around, and PlaylistMuse takes it from there.

The AI provider you choose interprets that request, real catalogue data resolves it into actual, playable tracks, and you stay in control of the result: review it, edit it, refine it, keep it in your local library, or publish it straight to YouTube Music.

It runs entirely on infrastructure you control. The core application only needs an AI provider to work; Last.fm and YouTube Music are optional integrations you can turn on whenever you want them, independently of each other.

## Why PlaylistMuse

- **Your data stays on your server.** No account, no cloud sync, no third party storing your listening habits or your prompts.
- **You choose the AI.** Bring your own Gemini, OpenAI, Anthropic, OpenRouter, Ollama, or any OpenAI-compatible endpoint, including fully local models, at no cost beyond what you already pay for that provider.
- **Real tracks, not hallucinated ones.** Every generated playlist is resolved and validated against real catalogue data instead of trusting the AI's raw output.
- **Built to be refined, not just generated.** Playlist Studio lets you lock the tracks you like and re-run a request against only the part you want to change.
- **Free and open source.** MIT licensed, self-hosted, no subscription, no lock-in.

## Screenshots

<p align="center">
  <img src="docs/media/screenshot-generation.png" alt="Describing a playlist from a text prompt in PlaylistMuse" width="800">
  <br><em>Describe the playlist you want, in plain language.</em>
</p>

<p align="center">
  <img src="docs/media/screenshot-playlist.png" alt="A generated playlist resolved against the real YouTube Music catalogue" width="800">
  <br><em>Real tracks, resolved from the real catalogue and ready to review.</em>
</p>

<p align="center">
  <img src="docs/media/screenshot-studio.png" alt="Reviewing and refining a playlist in Playlist Studio" width="800">
  <br><em>Lock the tracks you like, refine only the rest with Playlist Studio.</em>
</p>

<p align="center">
  <img src="docs/media/screenshot-library.png" alt="The PlaylistMuse local playlist library" width="800">
  <br><em>Every playlist stays in your local library.</em>
</p>

<p align="center">
  <img src="docs/media/screenshot-statistics.png" alt="PlaylistMuse statistics overview" width="800">
  <br><em>See what you've generated over time, computed locally.</em>
</p>

<p align="center">
  <img src="docs/media/screenshot-settings.png" alt="Connecting an AI provider in PlaylistMuse settings" width="800">
  <br><em>Bring your own AI provider.</em>
</p>

## Features

| | Capability | Description |
|---|---|---|
| 🎧 | **Playlist generation** | Create playlists from natural-language requests or a reference song. |
| 🧠 | **AI-powered curation** | Use the AI provider of your choice to interpret musical direction and constraints. |
| ✨ | **Review and refinement** | Review the result, edit playlist content and refine drafts before publishing. |
| 📚 | **Persistent library** | Keep generated playlists in local persistent storage and reopen them later. |
| 🌐 | **Music discovery** | Optionally use Last.fm to broaden discovery and provide additional music signals. |
| ▶️ | **YouTube Music publishing** | Connect a YouTube Music account and publish completed playlists directly from PlaylistMuse. |
| 🛡️ | **Validation and diagnostics** | Validate resolved tracks and requests, and collect sanitized diagnostics when technical support is needed. |

### How it works

PlaylistMuse starts from the musical direction you provide, either as a natural-language request or a reference song. The configured AI provider interprets that intent and, when enabled, optional discovery signals help broaden the selection. PlaylistMuse then resolves the proposed tracks against real catalogue data and presents the result for review. You can refine the playlist before keeping it in the local library or publishing it to YouTube Music when that integration is connected.

## Quick start

For a first try, the Docker image needs a persistent data folder and a single command:

```bash
mkdir -p playlistmuse/data && cd playlistmuse
docker run -d \
  --name playlistmuse \
  --restart unless-stopped \
  -p 5780:5780 \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/steventrux/playlistmuse:latest
```

Open `http://localhost:5780`, add at least one AI provider from the settings page, and generate your first playlist. See [Installation](#installation) below for the full walkthrough, alternative setups and upgrade notes, and [Configuration](#configuration) for connecting Last.fm and YouTube Music.

## Installation

PlaylistMuse can be installed with Docker or run directly with Python. The published Docker image is the recommended method because it provides a self-contained environment and straightforward upgrades, while the native Python installation is available for users who prefer to run the application directly on the host.

### Docker installation **(Recommended)**

#### Requirements

- Docker Engine or Docker Desktop.
- A host port available for PlaylistMuse. The examples below use `5780`.
- Persistent local storage for the application `data` directory.
- Network access from the container to the AI provider and any optional services you configure.

#### Install the latest stable release

Create a directory for PlaylistMuse and its persistent data:

```bash
mkdir -p playlistmuse/data
cd playlistmuse
```

Pull the latest stable image:

```bash
docker pull ghcr.io/steventrux/playlistmuse:latest
```

Start PlaylistMuse:

```bash
docker run -d \
  --name playlistmuse \
  --restart unless-stopped \
  -p 5780:5780 \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/steventrux/playlistmuse:latest
```

Open:

```text
http://localhost:5780
```

On first use, configure at least one AI provider from the PlaylistMuse interface. Last.fm and YouTube Music can be configured later if required.

#### Use a different host port

To expose PlaylistMuse on a different host port, change the first value in the port mapping. For example:

```bash
docker run -d \
  --name playlistmuse \
  --restart unless-stopped \
  -p 8080:5780 \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/steventrux/playlistmuse:latest
```

Then open `http://localhost:8080`.

#### Run a specific release

To stay on a specific published version, replace `latest` with the desired release tag:

```text
ghcr.io/steventrux/playlistmuse:<version>
```

Using a versioned tag prevents an installation from moving to a newer release when the image is pulled again.

### Native Python installation

A native installation runs PlaylistMuse directly from the repository without Docker.

#### Requirements

- Python 3.12
- Git
- `pip`
- Python virtual environment support (`venv`)
- Network access to the AI provider and any optional services you configure

Clone the repository:

```bash
git clone https://github.com/steventrux/PlaylistMuse.git
cd PlaylistMuse
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.venv\Scripts\Activate.ps1
```

Install the application dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create the persistent data directory:

```bash
mkdir -p data
```

Start PlaylistMuse:

```bash
uvicorn backend.application:app --host 0.0.0.0 --port 5780
```

Open:

```text
http://localhost:5780
```

PlaylistMuse stores its persistent state in the local `data` directory by default. The location can be changed with the `PLAYLISTMUSE_DATA_DIR` environment variable.

For a permanent deployment, run the Uvicorn command with the process or service manager appropriate for your operating system.

### Build from source with Docker Compose

Docker Compose can be used when you want to build the repository code locally while keeping a containerized installation.

Requirements:

- Git
- Docker Engine or Docker Desktop
- Docker Compose v2

```bash
git clone https://github.com/steventrux/PlaylistMuse.git
cd PlaylistMuse
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:5780`.

The repository Compose configuration stores application data in `./data`.

## Configuration

PlaylistMuse is designed to be configured primarily from the web interface. Configuration is stored in the persistent application data directory.

| Service | Required | Purpose |
|---|---|---|
| **AI provider** | Yes | Interprets playlist requests and powers generation and refinement. |
| **Last.fm** | No | Adds optional discovery signals and related music information. |
| **YouTube Music** | No | Publishes finished playlists to a connected account. |

### AI provider

At least one AI provider must be configured before PlaylistMuse can generate playlists.

Open the AI settings, choose a provider and enter the required connection details. PlaylistMuse can keep provider profiles so you can configure more than one provider and select which configured provider is active.

Supported provider types include:

| Provider | Typical configuration |
|---|---|
| **Google Gemini** | API key and model |
| **OpenAI** | API key and model |
| **Anthropic** | API key and model |
| **OpenRouter** | OpenRouter API key; Auto and Free routing profiles are supported |
| **Ollama** | Ollama base URL and model |
| **OpenAI-compatible endpoint** | Endpoint base URL, model and an API key when required by the service |

Any OpenAI-compatible endpoint also covers other hosted providers, for example Groq, Mistral, DeepSeek or Qwen, as long as you point PlaylistMuse at the provider's base URL and API key.

Where supported, optional fallback models can be saved together with the primary model.

API keys are credentials. Do not include them in screenshots, issues or diagnostic attachments.

### Last.fm

Last.fm is optional. PlaylistMuse continues to generate playlists when it is not configured.

To enable it:

1. Create a Last.fm API account and obtain an API key.
2. Open the Last.fm settings in PlaylistMuse.
3. Enter and save the API key.

For deployments that prefer environment-based configuration, the key can also be supplied as:

```env
PLAYLISTMUSE_LASTFM_API_KEY=your_api_key
```

An optional request timeout can be set with `PLAYLISTMUSE_LASTFM_TIMEOUT_SECONDS`. See `.env.example` for the supported deployment variables.

### YouTube Music

YouTube Music is optional and is required only for direct publishing from PlaylistMuse.

PlaylistMuse uses Google's OAuth device authorization flow. To configure it:

1. Create or select a project in Google Cloud Console.
2. Enable **YouTube Data API v3** for that project.
3. Configure the project's OAuth consent screen as required for your account and application status.
4. Create an OAuth client of type **TVs and Limited Input devices**.
5. Copy the OAuth client ID and client secret.
6. Open the YouTube Music settings in PlaylistMuse and save those credentials.
7. Select **Connect account**.
8. Follow the Google device-authorization instructions shown by PlaylistMuse and approve access with the YouTube/YouTube Music account you want to use.
9. Return to PlaylistMuse and verify that the account is shown as connected.

If Google authorization is later revoked or expires, reconnect the account from PlaylistMuse. Changing the configured OAuth client also requires a new account authorization.

Publishing depends on YouTube services and the quota available to the configured Google Cloud project.

### Environment configuration

PlaylistMuse uses `data` as its default persistent data directory for native runs. The published container uses `/app/data`, which the recommended Docker command maps to `./data` on the host.

The repository includes `.env.example` for deployment-level options. The web interface remains the recommended place to manage service credentials and provider profiles because saved settings persist in the application data directory.

## Data, backup and updates

### Persistent data

PlaylistMuse keeps its persistent state in a single application data directory. With the recommended Docker installation this is the host `./data` directory mounted at `/app/data`; with the native Python installation it is `./data` by default.

The directory includes the playlist library, application settings, service credentials and authorization data, and diagnostic logs. Treat the complete directory as private application data.

Do not run PlaylistMuse without persistent storage if you expect settings and playlists to survive upgrades, container replacement or service restarts.

### Backup

Stop the running PlaylistMuse instance before taking a filesystem-level backup whenever possible, then copy the complete `data` directory to your backup location while preserving its contents and file structure.

Back up the complete directory rather than individual database files. This keeps the playlist database and related configuration in a consistent set.

### Restore

1. Stop the running PlaylistMuse instance.
2. Keep a copy of the current `data` directory in case you need to undo the restore.
3. Replace the current contents with the complete backup.
4. Ensure PlaylistMuse can read and write the restored files.
5. Start PlaylistMuse and verify the library and configured services.

### Update the stable Docker installation

Back up the `data` directory before updating.

Pull the current stable image:

```bash
docker pull ghcr.io/steventrux/playlistmuse:latest
```

Recreate PlaylistMuse with the same persistent `data` directory and the new image. If you use a custom host port or additional Docker options, preserve the same deployment settings during the update.

### Update a native Python installation

Back up the `data` directory before updating, then update the repository and reinstall the declared dependencies inside the existing virtual environment:

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1` instead.

Restart the PlaylistMuse process after the update. The existing `data` directory is reused automatically unless `PLAYLISTMUSE_DATA_DIR` points to another location.

### Remote access

PlaylistMuse is self-hosted and may contain API credentials and account authorization data. Do not expose the application directly to the public internet without an appropriate access-control layer.

For access beyond the local host or trusted local network, use a secure private network or a properly configured HTTPS reverse proxy with authentication.

## Roadmap

PlaylistMuse is under active development. Areas currently planned or in progress include:

- Excluded artists and tracks, with per-playlist overrides, alongside the existing favorites.
- Appending generated tracks to an existing playlist instead of only creating new ones.
- Importing a YouTube Music playlist by ID.
- Light / dark / automatic theme.

There are no fixed dates for these items. Feature requests and votes on priorities are welcome through [GitHub Issues](https://github.com/steventrux/PlaylistMuse/issues).

## Support and feedback

GitHub Issues is the official place for PlaylistMuse support reports.

Use **Playlist result feedback** when PlaylistMuse works technically but the generated or refined playlist does not follow the musical request as expected. The in-app **Give feedback** action prepares the relevant playlist context automatically.

Use **Bug report** for errors, crashes, broken functionality or other reproducible technical problems. When available, include the `PM-...` error reference shown by PlaylistMuse and attach a diagnostic report from **Settings → Diagnostics**.

Before sharing diagnostics, review the archive and remove anything you do not want to publish. Never attach `.env`, raw credential files, API keys, passwords, cookies or OAuth tokens to a public issue.

See **[SUPPORT.md](SUPPORT.md)** for the complete support guide, troubleshooting steps, diagnostic information, privacy guidance and reporting checklist.

## Contributing

Contributions, bug reports and feature suggestions are welcome. Before opening a pull request:

- Check open issues to avoid duplicate work.
- Keep changes focused and, where practical, covered by tests.
- Follow the existing code style in the file you are editing.

If you are unsure whether a change fits the project's direction, open an issue to discuss it first.

## Disclaimer

PlaylistMuse is an independent project and is not affiliated with Google, YouTube, Last.fm or any supported AI provider.

External services and APIs used by PlaylistMuse may change independently of the project and may have their own quotas, availability limits, terms and authentication requirements.

## License

PlaylistMuse is released under the [MIT License](LICENSE).
