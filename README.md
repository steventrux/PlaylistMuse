<div align="center">
  <img alt="PlaylistMuse" src="frontend/playlistmuse-banner.svg" width="100%">

  <p>
    Built for people who would rather describe a sound than manually assemble a queue.
  </p>

  <br>

  <a href="https://github.com/steventrux/PlaylistMuse/releases/latest"><img src="https://img.shields.io/github/v/release/steventrux/PlaylistMuse?style=flat-square&label=release" alt="Latest release" height="24"></a>
  <a href="https://github.com/steventrux/PlaylistMuse/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://img.shields.io/github/actions/workflow/status/steventrux/PlaylistMuse/ci.yml?branch=main&style=flat-square&label=CI&logo=github" alt="CI status" height="24"></a>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" height="24">
  <img src="https://img.shields.io/badge/FastAPI-0.116+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" height="24">
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker ready" height="24">
  <img src="https://img.shields.io/badge/self--hosted-yes-8B5CF6?style=flat-square" alt="Self-hosted" height="24">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/steventrux/PlaylistMuse?style=flat-square&color=EC4899" alt="MIT license" height="24"></a>

  <p>
    Create, refine, save and publish YouTube Music playlists from a written idea or a reference song.
  </p>

  <p>
    <a href="#features"><strong>Features</strong></a>
    &nbsp;·&nbsp;
    <a href="#installation"><strong>Installation</strong></a>
    &nbsp;·&nbsp;
    <a href="#configuration"><strong>Configuration</strong></a>
    &nbsp;·&nbsp;
    <a href="#data-backup-and-updates"><strong>Data & backup</strong></a>
    &nbsp;·&nbsp;
    <a href="#support-and-feedback"><strong>Support</strong></a>
  </p>
</div>

<br>

## Overview

PlaylistMuse is a self-hosted web application for creating music playlists with natural-language instructions.

Describe the sound, mood, era, activity or musical direction you want, or start from a reference track. PlaylistMuse uses the AI provider you choose to build a playlist from real catalogue tracks, lets you review and refine the result, stores your playlists locally and can publish finished playlists to YouTube Music.

The core application works with an AI provider only. Last.fm and YouTube Music are optional integrations that can be enabled independently.

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

1. **Describe the playlist** — enter a prompt or choose a reference song.
2. **Generate** — PlaylistMuse combines your request with the configured AI provider and optional discovery signals.
3. **Review and refine** — inspect the playlist and make any changes you want before publishing.
4. **Save or publish** — keep the playlist in the local library or publish it to YouTube Music when the integration is connected.

## Installation

The recommended installation uses the published Docker image. Application data must be stored outside the container so that settings, credentials and playlists survive container replacement and upgrades.

### Requirements

- Docker Engine or Docker Desktop.
- A host port available for PlaylistMuse. The examples below use `5780`.
- Persistent local storage for the application `data` directory.
- Network access from the container to the AI provider and any optional services you configure.

Git and Docker Compose are required only when building PlaylistMuse from source.

### Install the latest stable release

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

### Use a different host port

Only the port on the left side of the mapping changes. For example, to expose PlaylistMuse on port `8080`:

```bash
docker run -d \
  --name playlistmuse \
  --restart unless-stopped \
  -p 8080:5780 \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/steventrux/playlistmuse:latest
```

Then open `http://localhost:8080`.

### Run a specific release

To stay on a specific published version, replace `latest` with the desired release tag:

```text
ghcr.io/steventrux/playlistmuse:<version>
```

Using a versioned tag prevents an installation from moving to a newer release when the image is pulled again.

### Stop and start

```bash
docker stop playlistmuse
docker start playlistmuse
```

### Remove the container

Removing the container does not remove the bind-mounted `data` directory:

```bash
docker rm -f playlistmuse
```

### Build from source

Building from source is intended for users who specifically want to run the repository code rather than the published image.

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

To stop the source installation:

```bash
docker compose down
```

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

The published container already uses `/app/data` as its persistent data directory. The bind mount shown in the installation instructions maps that directory to `./data` on the host.

The repository includes `.env.example` for deployment-level options. The web interface remains the recommended place to manage service credentials and provider profiles because saved settings persist in the application data directory.

## Data, backup and updates

### Persistent data

All persistent PlaylistMuse state is stored under `/app/data` inside the container. With the recommended installation command, this corresponds to the host `./data` directory.

It includes the playlist library, application settings, service credentials and authorization data, and diagnostic logs. Treat the complete directory as private application data.

Do not run PlaylistMuse without persistent storage if you expect settings and playlists to survive container replacement.

### Backup

For the safest filesystem-level backup, stop PlaylistMuse first:

```bash
docker stop playlistmuse
```

Copy the complete `data` directory to your backup location, preserving its contents and file structure, then restart PlaylistMuse:

```bash
docker start playlistmuse
```

Back up the complete directory rather than individual database files. This keeps the playlist database and related configuration in a consistent set.

### Restore

1. Stop the PlaylistMuse container.
2. Keep a copy of the current `data` directory in case you need to undo the restore.
3. Replace the current contents with the complete backup.
4. Ensure the container can read and write the restored files.
5. Start PlaylistMuse and verify the library and configured services.

### Update the stable Docker installation

Back up the `data` directory before updating.

Pull the current stable image:

```bash
docker pull ghcr.io/steventrux/playlistmuse:latest
```

Replace the existing container:

```bash
docker rm -f playlistmuse

docker run -d \
  --name playlistmuse \
  --restart unless-stopped \
  -p 5780:5780 \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/steventrux/playlistmuse:latest
```

The persistent `data` directory is reused by the new container.

When using a custom host port or additional Docker options, reuse the same options when recreating the container.

### Remote access

PlaylistMuse is self-hosted and may contain API credentials and account authorization data. Do not expose the application directly to the public internet without an appropriate access-control layer.

For access beyond the local host or trusted local network, use a secure private network or a properly configured HTTPS reverse proxy with authentication.

## Support and feedback

GitHub Issues is the official place for PlaylistMuse support reports.

Use **Playlist result feedback** when PlaylistMuse works technically but the generated or refined playlist does not follow the musical request as expected. The in-app **Give feedback** action prepares the relevant playlist context automatically.

Use **Bug report** for errors, crashes, broken functionality or other reproducible technical problems. When available, include the `PM-...` error reference shown by PlaylistMuse and attach a diagnostic report from **Settings → Diagnostics**.

Before sharing diagnostics, review the archive and remove anything you do not want to publish. Never attach `.env`, raw credential files, API keys, passwords, cookies or OAuth tokens to a public issue.

See **[SUPPORT.md](SUPPORT.md)** for the complete support guide, troubleshooting steps, diagnostic information, privacy guidance and reporting checklist.

## Disclaimer

PlaylistMuse is an independent project and is not affiliated with Google, YouTube, Last.fm or any supported AI provider.

External services and APIs used by PlaylistMuse may change independently of the project and may have their own quotas, availability limits, terms and authentication requirements.

## License

PlaylistMuse is released under the [MIT License](LICENSE).
