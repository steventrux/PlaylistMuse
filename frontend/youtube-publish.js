(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const $ = (id) => document.getElementById(id);
  let playlist = null;

  try {
    playlist = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
  } catch {
    playlist = null;
  }

  async function readJson(response) {
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(text || `HTTP ${response.status}`);
    }
    if (!response.ok) {
      const detail = payload.detail ?? payload.error ?? payload.message;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || payload));
    }
    return payload;
  }

  function setStatus(text, kind = '') {
    const element = $('youtube-publish-status');
    element.replaceChildren();
    element.textContent = text;
    element.classList.toggle('error', kind === 'error');
    element.classList.toggle('success', kind === 'success');
  }

  function setPublishingButton(button) {
    const spinner = document.createElement('span');
    spinner.className = 'generation-spinner';
    spinner.setAttribute('aria-hidden', 'true');

    const label = document.createElement('span');
    label.className = 'generation-label';
    label.textContent = 'Creating';

    const dots = document.createElement('span');
    dots.className = 'generation-dots';
    dots.setAttribute('aria-hidden', 'true');
    dots.append(
      document.createElement('span'),
      document.createElement('span'),
      document.createElement('span'),
    );

    button.replaceChildren(spinner, label, dots);
    button.classList.add('is-loading');
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');

    return () => {
      button.classList.remove('is-loading');
      button.removeAttribute('aria-busy');
      button.disabled = false;
      button.textContent = 'Create on YouTube Music';
    };
  }

  async function refreshStatus() {
    const button = $('create-youtube-playlist');
    const summary = $('youtube-publish-account');

    try {
      const status = await readJson(await fetch('/api/youtube/status'));
      if (status.account_connected) {
        button.disabled = false;
        summary.textContent = status.account_name
          ? `Connected as ${status.account_name}`
          : 'YouTube Music account connected';
      } else {
        button.disabled = true;
        summary.textContent = status.credentials_configured
          ? 'Account not connected · connect it from Settings on the home page'
          : 'Google OAuth client not configured · open Settings on the home page';
      }
    } catch {
      button.disabled = true;
      summary.textContent = 'Unable to check the YouTube Music connection';
    }
  }

  async function publishPlaylist() {
    if (!playlist || !Array.isArray(playlist.tracks)) {
      setStatus('No generated playlist is available in this browser session.', 'error');
      return;
    }

    const title = $('playlist-name').value.trim();
    const videoIds = playlist.tracks
      .map((track) => String(track.video_id || '').trim())
      .filter(Boolean);

    if (!title) {
      setStatus('Enter a playlist title before publishing.', 'error');
      $('playlist-name').focus();
      return;
    }
    if (videoIds.length !== playlist.tracks.length) {
      setStatus('One or more tracks do not have a valid YouTube Music ID.', 'error');
      return;
    }

    const button = $('create-youtube-playlist');
    const resetButton = setPublishingButton(button);
    setStatus('Creating the playlist in your YouTube Music account…');

    try {
      const result = await readJson(await fetch('/api/youtube/playlists', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          title,
          description: playlist.description || playlist.prompt || '',
          privacy_status: $('youtube-privacy').value,
          video_ids: videoIds,
        }),
      }));

      playlist.youtube_playlist = result;
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(playlist));

      button.classList.remove('is-loading');
      button.removeAttribute('aria-busy');
      button.disabled = true;
      button.textContent = 'Created on YouTube Music';

      const status = $('youtube-publish-status');
      status.replaceChildren();
      status.classList.remove('error');
      status.classList.add('success');
      status.append('Playlist created successfully · ');
      const link = document.createElement('a');
      link.href = result.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Open in YouTube Music';
      status.append(link);
    } catch (error) {
      resetButton();
      setStatus(error.message || String(error), 'error');
    }
  }

  $('create-youtube-playlist').addEventListener('click', publishPlaylist);
  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  refreshStatus();
})();
