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
    Create, save, refine and publish YouTube Music playlists from a written idea or a reference song.
  </p>

  <p>
    <a href="#what-playlistmuse-does"><strong>Features</strong></a>
    &nbsp;·&nbsp;
    <a href="#from-idea-to-playlist"><strong>How it works</strong></a>
    &nbsp;·&nbsp;
    <a href="#installation"><strong>Installation</strong></a>
    &nbsp;·&nbsp;
    <a href="#configuration"><strong>Configuration</strong></a>
    &nbsp;·&nbsp;
    <a href="#support-and-feedback"><strong>Support</strong></a>
  </p>
</div>

<br>

## What PlaylistMuse does

PlaylistMuse is a self-hosted web application that turns a musical idea into an editable YouTube Music playlist.

Describe a mood, genre, era, activity, journey or any combination of musical constraints, or start from an existing song. PlaylistMuse uses the AI provider you choose, resolves the request against real catalogue tracks and prepares a playlist that you can review before publishing.

Generated playlists are saved automatically in a local library, so they remain available after the browser or container restarts. Last.fm can optionally add discovery signals and random seed suggestions. Connecting YouTube Music is only required when you want to publish directly from PlaylistMuse.

### Create and understand the request

- Generate playlists from a natural-language prompt or a seed song.
- Choose between 5 and 100 tracks.
- Exclude live recordings, covers and remixes, or explicitly request those recording versions in the prompt.
- Receive a warning when the written request conflicts with an enabled recording filter.
- Inspect request complexity and clarity before generation.
- Use **Surprise me** for a random prompt, or let Last.fm suggest a random seed when configured.

### Refine before publishing

- Edit the playlist title and description.
- Add, remove or replace individual tracks.
- Use **Playlist Studio** to fine-tune a saved draft with a natural-language instruction.
- Choose exactly which tracks Playlist Studio may edit and lock tracks that must remain unchanged.
- Preview proposed substitutions before applying them.
- Apply precise constraints such as artist counts and recording-version requirements during generation and refinement.
- Keep published playlists protected from draft-only editing operations.

### Keep a local playlist library

- Save generated playlists automatically in persistent storage.
- Reopen drafts and published playlists later.
- Search, sort and filter the library by status.
- Add and manage playlist tags.
- Keep the YouTube Music link associated with playlists that have already been published.

### Improve discovery with Last.fm

Last.fm is optional. When enabled, PlaylistMuse can use related artists, tracks and listening signals to broaden discovery beyond the most obvious AI suggestions while keeping the original request as the primary guide.

### Publish to YouTube Music

Review the final sequence, choose Private, Unlisted or Public visibility, and create the playlist directly in your YouTube Music account. PlaylistMuse also assembles a cover mosaic from representative track artwork for the local playlist view.

### Share playlist-result feedback

If a generated or refined playlist does not match what you asked for, use **Give feedback** from the playlist page. PlaylistMuse opens a structured GitHub Playlist result feedback issue with the relevant request and playlist context prefilled. Playlist-result feedback is kept separate from technical bug reports.

### Diagnose problems safely

PlaylistMuse keeps a small set of rotating application logs and can generate a diagnostic ZIP from **Settings → Diagnostics**. Server-side failures include a `PM-...` reference that can be matched with the related log entry. Diagnostic reports are sanitized before download and are designed to be attached to the project bug-report form.

## From idea to playlist

1. **Describe what you want** — write a prompt or choose a song as the starting point.
2. **Shape the direction** — the selected AI provider interprets the request and, when enabled, Last.fm adds discovery context.
3. **Match real tracks** — PlaylistMuse resolves title, artist and catalogue information, removes duplicates and validates requested constraints against the resolved tracks.
4. **Review and refine** — edit metadata and tracks, or use Playlist Studio to refine all or selected parts of a draft and preview the changes before applying them.
5. **Save automatically** — the playlist is kept in the local library and can be reopened later.
6. **Publish when ready** — send the finished playlist to YouTube Music and retain its remote link in the library.

## Installation

> **Recommended setup:** run the published Docker image and store application data in a persistent local directory.

### Requirements

- Docker Engine

### Run the latest stable release

```bash
git clone https://github.com/steventrux/PlaylistMuse.git
cd PlaylistMuse
cp .env.example .env
mkdir -p data

docker run -d \
  --name playlistmuse \
  --restart unless-stopped \
  -p 5780:5780 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  ghcr.io/steventrux/playlistmuse:latest
```

Open **http://localhost:5780**.

The initial setup guides you through the required AI provider configuration and the optional YouTube Music connection.

### Update

Back up the `data` directory first, then pull the current stable image:

```bash
docker pull ghcr.io/steventrux/playlistmuse:latest
docker rm -f playlistmuse
```

Run the installation command again after pulling the new image.

Use a versioned image tag such as `ghcr.io/steventrux/playlistmuse:0.2.2` when you want to remain on a specific published release.

### Stop

```bash
docker rm -f playlistmuse
```

<details>
<summary><strong>Build from source</strong></summary>

<br>

Docker Compose v2 is required for this installation method.

```bash
git clone https://github.com/steventrux/PlaylistMuse.git
cd PlaylistMuse
cp .env.example .env
docker compose up -d --build
```

To stop the Docker Compose installation:

```bash
docker compose down
```

</details>

## Configuration

| Service | Required | Purpose |
|---|---|---|
| **AI provider** | Yes | Interprets requests and creates or refines playlists. |
| **Last.fm** | No | Adds discovery signals and optional random seed suggestions. |
| **YouTube Music** | No | Publishes finished playlists directly to your account. |

### AI provider

Credentials, models and saved profiles are managed from the web interface.

PlaylistMuse supports:

- Google Gemini
- OpenAI
- Anthropic
- OpenRouter Auto and OpenRouter Free
- Ollama
- OpenAI-compatible endpoints

### Last.fm

Add an API key from the Last.fm settings page or through `PLAYLISTMUSE_LASTFM_API_KEY` in `.env`.

Playlist generation continues to work normally when Last.fm is not configured.

### YouTube Music

To enable direct publishing:

1. Create or select a project in Google Cloud Console.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen.
4. Create an OAuth client of type **TVs and Limited Input devices**.
5. Enter the client ID and secret in PlaylistMuse.
6. Select **Connect account** and complete the authorization.

## Data, backup and remote access

Settings, credentials, authorization data, diagnostic logs and the playlist library are stored in the persistent `./data` directory.

The playlist library uses `data/playlists.db`. SQLite may also create `playlists.db-wal` and `playlists.db-shm` while the application is running. Recent diagnostic logs are kept under `data/logs` and rotate automatically.

Back up the complete `data` directory before moving or updating the installation. For the most consistent backup, stop the container first or use an SQLite-aware backup tool.

For remote access, use a trusted private network or protect PlaylistMuse with HTTPS and authentication.

## Support and feedback

Use **Give feedback** from a playlist when the generated or refined result did not match the request. This creates a dedicated Playlist result feedback issue with useful playlist context already included.

Use the repository **Bug report** form for technical problems such as errors, crashes or broken functionality. Include the PlaylistMuse version/build, installation method, browser and operating system, steps to reproduce, expected and actual behavior, and any `PM-...` error reference shown by the application.

For the most useful technical report, open **Settings → Diagnostics**, download the diagnostic ZIP and attach it to the issue. PlaylistMuse redacts known credentials and common secret formats, but you should still review the archive before sharing it.

Never upload `.env`, raw configuration files, API keys, cookies or OAuth token files. See [SUPPORT.md](SUPPORT.md) for the complete reporting guide.

## Disclaimer

PlaylistMuse is an independent project and is not affiliated with Google, YouTube or Last.fm.

YouTube Music access relies on third-party and Google APIs that may change over time.

## License

PlaylistMuse is released under the [MIT License](LICENSE).
