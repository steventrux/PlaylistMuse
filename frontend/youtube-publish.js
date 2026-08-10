(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;
  const publishSection = document.querySelector('.youtube-publish');
  let playlist = null;
  let selectedPrivacy = 'PRIVATE';

  function loadFooterStatus() {
    if (document.querySelector('script[data-playlistmuse-footer-status]')) return;
    const script = document.createElement('script');
    script.src = '/static/home-status.js?v=14';
    script.dataset.playlistmuseFooterStatus = 'true';
    document.body.append(script);
  }

  try {
    playlist = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
  } catch {
    playlist = null;
  }

  function setPublishState(state = 'ready') {
    publishSection?.classList.toggle('is-publishing', state === 'publishing');
    publishSection?.classList.toggle('is-success', state === 'success');
  }

  function setStatus(text, kind = '') {
    const element = $('youtube-publish-status');
    element.replaceChildren();
    element.classList.remove('error', 'success');

    if (!text) {
      element.textContent = '';
      element.classList.add('hidden');
      return;
    }

    element.classList.remove('hidden');
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

  function showChecking() {
    const loading = $('youtube-publish-loading');
    const controls = $('youtube-publish-controls');
    setPublishState('checking');
    setStatus('');
    loading.classList.remove('hidden');
    $('youtube-publish-warning').classList.add('hidden');
    controls.classList.remove('is-success');
    controls.classList.add('hidden');
  }

  function hideChecking() {
    $('youtube-publish-loading').classList.add('hidden');
  }

  function showUnavailable(message) {
    const controls = $('youtube-publish-controls');
    setPublishState('unavailable');
    setStatus('');
    hideChecking();
    controls.classList.remove('is-success');
    controls.classList.add('hidden');
    $('youtube-publish-warning').classList.remove('hidden');
    $('youtube-publish-warning-text').textContent = message;
  }

  function showControls(alreadyPublished) {
    const controls = $('youtube-publish-controls');
    setPublishState('ready');
    setStatus('');
    hideChecking();
    controls.classList.remove('is-success');
    $('youtube-publish-warning').classList.add('hidden');
    controls.classList.remove('hidden');

    const button = $('create-youtube-playlist');
    button.disabled = alreadyPublished;
    setPrivacyDisabled(alreadyPublished);
  }

  function openYouTubeSettings() {
    const target = new URL('/static/settings.html', window.location.origin);
    target.searchParams.set('section', 'youtube');
    target.searchParams.set(
      'return',
      `${window.location.pathname}${window.location.search}${window.location.hash}` || '/',
    );
    window.location.assign(`${target.pathname}${target.search}`);
  }

  function renderPublishedResult(result) {
    if (!result?.url) return false;

    const controls = $('youtube-publish-controls');
    const button = $('create-youtube-playlist');
    setPublishState('success');
    hideChecking();
    if (button) {
      button.classList.remove('is-loading');
      button.removeAttribute('aria-busy');
      button.disabled = true;
    }

    $('youtube-publish-warning').classList.add('hidden');
    controls.classList.remove('hidden');
    controls.classList.add('is-success');
    controls.replaceChildren();
    controls.setAttribute('role', 'status');
    controls.setAttribute('aria-live', 'polite');

    const createdCount = Number(result.track_count || 0);
    const requestedCount = Number(result.requested_track_count || createdCount);

    const success = document.createElement('div');
    success.className = 'youtube-publish-success';

    const message = document.createElement('p');
    message.append(
      createdCount === requestedCount
        ? `Playlist created with ${createdCount} tracks · `
        : `Playlist created with ${createdCount} of ${requestedCount} tracks · `,
    );

    const link = document.createElement('a');
    link.href = result.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open in YouTube Music';
    message.append(link);
    success.append(message);

    if (result.warning) {
      const warning = document.createElement('span');
      warning.className = 'youtube-publish-success-warning';
      warning.textContent = result.warning;
      success.append(warning);
    }

    controls.append(success);
    setStatus('');
    return true;
  }

  async function refreshStatus() {
    const alreadyPublished = Boolean(playlist?.youtube_playlist?.url);
    if (alreadyPublished) {
      renderPublishedResult(playlist.youtube_playlist);
      return;
    }

    showChecking();
    try {
      const status = await readJson(await fetch('/api/youtube/status'));
      if (status.account_connected) {
        showControls(false);
      } else if (status.credentials_configured) {
        showUnavailable('Connect your Google account before publishing this playlist.');
      } else {
        showUnavailable('Configure Google OAuth before publishing this playlist.');
      }
    } catch {
      showUnavailable('The YouTube Music connection could not be checked.');
    }
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
    const thumbnailUrls = window.PlaylistMuseMosaic
      ?.selectMosaicUrls(playlist.tracks) || [];

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
    const resetButton = setLoadingButton(button, {
      label: 'Creating',
      resetText: 'Create on YouTube Music',
      onStart: () => setPrivacyDisabled(true),
      onReset: () => setPrivacyDisabled(false),
    });
    setPublishState('publishing');
    setStatus('');

    try {
      const result = await readJson(await fetch('/api/youtube/playlists', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          title,
          description: playlist.description || playlist.prompt || '',
          privacy_status: selectedPrivacy,
          video_ids: videoIds,
          thumbnail_urls: thumbnailUrls,
        }),
      }));

      playlist.youtube_playlist = result;
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(playlist));
      window.dispatchEvent(new CustomEvent('playlistmuse-playlist-published', {
        detail: result,
      }));
      renderPublishedResult(result);
    } catch (error) {
      resetButton();
      setPublishState('ready');
      setStatus(error.message || String(error), 'error');
    }
  }

  document.querySelectorAll('.youtube-privacy-option').forEach((button) => {
    button.addEventListener('click', () => selectPrivacy(button));
  });
  $('youtube-open-settings').addEventListener('click', openYouTubeSettings);
  $('create-youtube-playlist').addEventListener('click', publishPlaylist);
  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  loadFooterStatus();
  refreshStatus();
})();
