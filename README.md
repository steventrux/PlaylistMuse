<div align="center">
  <img alt="PlaylistMuse" src="frontend/playlistmuse-banner.svg" width="100%">

  <p>
    Built for people who would rather describe a sound than manually assemble a queue.
  </p>

  <br>

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
    <a href="#playlistmuse-at-a-glance"><strong>Overview</strong></a>
    &nbsp;·&nbsp;
    <a href="#from-idea-to-playlist"><strong>How it works</strong></a>
    &nbsp;·&nbsp;
    <a href="#installation"><strong>Installation</strong></a>
    &nbsp;·&nbsp;
    <a href="#configuration"><strong>Configuration</strong></a>
  </p>
</div>

<br>

## PlaylistMuse at a glance

PlaylistMuse is a self hosted web application that turns a musical idea into an editable YouTube Music playlist.

Describe a mood, genre, era, activity or journey, or begin with an existing song. PlaylistMuse uses the AI provider you choose, finds matching tracks in the YouTube Music catalogue and prepares a playlist that you can review before publishing.

Generated playlists are saved automatically in a local library, so they can be reopened after the browser or container restarts. Last.fm can optionally add listening based discovery signals. Connecting YouTube Music is only required when you want to publish directly from PlaylistMuse.

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>🎵 Create</h3>
      <p>Generate a playlist from a natural language prompt or a seed song, with between 5 and 100 tracks.</p>
    </td>
    <td width="50%" valign="top">
      <h3>✨ Refine</h3>
      <p>Exclude live recordings, covers and remixes, remove duplicates and replace individual songs.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>💾 Save</h3>
      <p>Keep generated playlists in the local library, reopen them later, duplicate drafts or remove entries you no longer need.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🔎 Discover</h3>
      <p>Use optional Last.fm signals to help the AI find related tracks and artists beyond the most obvious choices.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>▶️ Publish</h3>
      <p>Edit the title, review the sequence, create a cover mosaic and publish to YouTube Music with the visibility you prefer.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🗂️ Reopen</h3>
      <p>See whether a playlist is still a draft or has already been published, with its YouTube Music link retained.</p>
    </td>
  </tr>
</table>

## From idea to playlist

<table>
  <tr>
    <td width="8%" align="center"><strong>1</strong></td>
    <td><strong>Describe what you want</strong><br>Write a prompt or choose a song as the starting point.</td>
  </tr>
  <tr>
    <td width="8%" align="center"><strong>2</strong></td>
    <td><strong>Let the AI shape the direction</strong><br>The selected provider interprets your request and proposes a coherent sequence. When Last.fm is enabled, it can add related listening signals.</td>
  </tr>
  <tr>
    <td width="8%" align="center"><strong>3</strong></td>
    <td><strong>Match real catalogue tracks</strong><br>PlaylistMuse checks title, artist and album information, removes duplicates and rejects unwanted versions.</td>
  </tr>
  <tr>
    <td width="8%" align="center"><strong>4</strong></td>
    <td><strong>Review and save</strong><br>The generated playlist is saved automatically. You can edit its title, replace tracks, reopen it from My playlists or create an independent copy.</td>
  </tr>
  <tr>
    <td width="8%" align="center"><strong>5</strong></td>
    <td><strong>Publish when ready</strong><br>Send the finished playlist to YouTube Music and retain its remote link in the local library.</td>
  </tr>
</table>

## Installation

> **Recommended setup**
>
> Run the published Docker image and store application data in a persistent local directory.

### Requirements

1. Docker Engine

2. Docker Compose v2, only when building from source

### Run the published image

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

```bash
docker pull ghcr.io/steventrux/playlistmuse:latest
docker rm -f playlistmuse
```

Run the installation command again after pulling the new image.

Use a versioned image tag instead of `latest` when you want to keep a specific release.

### Stop

```bash
docker rm -f playlistmuse
```

<details>
<summary><strong>Build from source</strong></summary>

<br>

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

<table>
  <tr>
    <th align="left">Service</th>
    <th align="left">Required</th>
    <th align="left">Purpose</th>
  </tr>
  <tr>
    <td><strong>AI provider</strong></td>
    <td>Yes</td>
    <td>Interprets the request and creates the playlist.</td>
  </tr>
  <tr>
    <td><strong>Last.fm</strong></td>
    <td>No</td>
    <td>Adds listening based discovery signals.</td>
  </tr>
  <tr>
    <td><strong>YouTube Music</strong></td>
    <td>No</td>
    <td>Publishes the finished playlist directly to your account.</td>
  </tr>
</table>

### AI provider

Credentials, models and saved profiles are managed from the web interface.

PlaylistMuse supports Google Gemini, OpenAI, Anthropic, OpenRouter, Ollama and OpenAI compatible endpoints.

### Last.fm

Add an API key from the Last.fm settings panel or through `PLAYLISTMUSE_LASTFM_API_KEY` in `.env`.

Playlist generation continues to work normally when Last.fm is not configured.

### YouTube Music

To enable direct publishing:

1. Create or select a project in Google Cloud Console.

2. Enable **YouTube Data API v3**.

3. Configure the OAuth consent screen.

4. Create an OAuth client of type **TVs and Limited Input devices**.

5. Enter the client ID and secret in PlaylistMuse.

6. Select **Connect account** and complete the authorization.

## Data and access

Settings, credentials, authorization data and the local playlist library are stored in the persistent `./data` directory.

The playlist library uses `data/playlists.db`. SQLite may also create temporary `playlists.db-wal` and `playlists.db-shm` files while the application is running.

Back up the complete `data` directory before moving or updating the installation. For the most consistent backup, stop the container first or use an SQLite-aware backup tool.

For remote access, use a trusted private network or protect the application with HTTPS and authentication.

## Disclaimer

PlaylistMuse is an independent project and is not affiliated with Google, YouTube or Last.fm.

YouTube Music access relies on third party and Google APIs that may change over time.

## License

PlaylistMuse is released under the [MIT License](LICENSE).
