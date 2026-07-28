(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const $ = (id) => document.getElementById(id);
  let playlist = null;
  let selectedPrivacy = 'PRIVATE';

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

  function setPrivacyDisabled(disabled) {
    document.querySelectorAll('.youtube-privacy-option').forEach((button) => {
      button.disabled = disabled;
    });
  }

  function selectPrivacy(button) {
    selectedPrivacy = button.dataset.privacy || 'PRIVATE';
    document.querySelectorAll('.youtube-privacy-option').forEach((option) => {
      const active = option === button;
      option.classList.toggle('active', active);
      option.setAttribute('aria-pressed', String(active));
    });
  }

  function showUnavailable(message) {
    $('youtube-publish-controls').classList.add('hidden');
    $('youtube-publish-warning').classList.remove('hidden');
    $('youtube-publish-warning-text').textContent = message;
  }

  function showControls(accountLabel, alreadyPublished) {
    $('youtube-publish-warning').classList.add('hidden');
    $('youtube-publish-controls').classList.remove('hidden');
    $('youtube-publish-account').textContent = accountLabel;

    const button = $('create-youtube-playlist');
    button.disabled = alreadyPublished;
    setPrivacyDisabled(alreadyPublished);
  }

  function renderPublishedResult(result) {
    if (!result?.url) return false;

    const button = $('create-youtube-playlist');
    button.classList.remove('is-loading');
    button.removeAttribute('aria-busy');
    button.disabled = true;
    button.textContent = 'Created on YouTube Music';
    setPrivacyDisabled(true);

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
    return true;
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
    setPrivacyDisabled(true);

    return () => {
      button.classList.remove('is-loading');
      button.removeAttribute('aria-busy');
      button.disabled = false;
      button.textContent = 'Create on YouTube Music';
      setPrivacyDisabled(false);
    };
  }

  async function refreshStatus() {
    const alreadyPublished = Boolean(playlist?.youtube_playlist?.url);

    try {
      const status = await readJson(await fetch('/api/youtube/status'));
      if (status.account_connected) {
        const accountLabel = status.account_name
          ? `Connected as ${status.account_name}`
          : 'YouTube Music account connected';
        showControls(accountLabel, alreadyPublished);
      } else if (status.credentials_configured) {
        showUnavailable('Connect your Google account from Settings on the home page before publishing this playlist.');
      } else {
        showUnavailable('Configure Google OAuth from Settings on the home page before publishing this playlist.');
      }
    } catch {
      showUnavailable('The YouTube Music connection could not be checked. Return to Settings and verify the account.');
    }

    if (alreadyPublished) renderPublishedResult(playlist.youtube_playlist);
  }

  async function publishPlaylist() {
    if (!playlist || !Array.isArray(playlist.tracks)) {
      setStatus('No generated playlist is available in this browser session.', 'error');
      return;
    }
    if (playlist.youtube_playlist?.url) {
      renderPublishedResult(playlist.youtube_playlist);
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
          privacy_status: selectedPrivacy,
          video_ids: videoIds,
        }),
      }));

      playlist.youtube_playlist = result;
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(playlist));
      renderPublishedResult(result);
    } catch (error) {
      resetButton();
      setStatus(error.message || String(error), 'error');
    }
  }

  document.querySelectorAll('.youtube-privacy-option').forEach((button) => {
    button.addEventListener('click', () => selectPrivacy(button));
  });
  $('create-youtube-playlist').addEventListener('click', publishPlaylist);
  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  refreshStatus();
})();
