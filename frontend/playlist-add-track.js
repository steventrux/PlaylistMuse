(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const LIBRARY_ENDPOINT = '/api/library/playlists';
  const SEARCH_ENDPOINT = '/api/seeds/search';
  const MAX_TRACKS = 100;
  const SEARCH_LIMIT = 8;
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;

  const trigger = $('add-track');
  const host = $('playlist-add-track-host');
  const titleInput = $('playlist-name');
  const descriptionInput = $('playlist-description');
  const draftActions = $('playlist-draft-actions');
  if (!trigger || !host) return;

  let results = [];
  let descriptionTimer = null;

  function readStoredJson(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || 'null');
    } catch {
      return null;
    }
  }

  function currentPlaylist() {
    return readStoredJson(STORAGE_KEY);
  }

  function generationRequest() {
    return readStoredJson(REQUEST_KEY);
  }

  function writePlaylist(playlist) {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(playlist));
  }

  function writeGenerationRequest(request) {
    sessionStorage.setItem(REQUEST_KEY, JSON.stringify(request));
  }

  function playlistDocument(playlist) {
    const document = JSON.parse(JSON.stringify(playlist));
    delete document.library_id;
    // See the matching comment in playlist.js: a cached tags snapshot here can
    // predate the background AI tag suggestion and would silently overwrite it.
    delete document.tags;
    return document;
  }

  function requestBody(playlist) {
    return JSON.stringify({
      playlist: playlistDocument(playlist),
      generation_request: generationRequest() || null,
    });
  }

  function isPublished() {
    return Boolean(currentPlaylist()?.youtube_playlist?.url);
  }

  function syncEditorState() {
    const playlist = currentPlaylist();
    const editable = Boolean(playlist && Array.isArray(playlist.tracks) && !playlist.youtube_playlist?.url);
    document.body.classList.toggle('playlist-readonly', !editable);
    if (titleInput) {
      titleInput.readOnly = !editable;
      titleInput.setAttribute('aria-readonly', String(!editable));
      titleInput.title = editable ? 'Edit playlist title' : 'Published playlist title';
    }
    if (descriptionInput) {
      descriptionInput.readOnly = !editable;
      descriptionInput.setAttribute('aria-readonly', String(!editable));
      descriptionInput.title = editable ? 'Edit playlist description' : 'Published playlist description';
    }
    draftActions?.classList.toggle('hidden', !editable);
    if (!editable) {
      host.replaceChildren();
      trigger.setAttribute('aria-expanded', 'false');
    }
  }

  function trackHistoryText(track) {
    const title = String(track?.title || 'Unknown track').trim();
    const artists = String(track?.artists || track?.artist || '').trim();
    return artists ? `${title} — ${artists}` : title;
  }

  function appendManualHistory(kind, track) {
    const request = generationRequest() || {};
    const refinements = Array.isArray(request.refinements) ? [...request.refinements] : [];
    const action = kind === 'manual_remove' ? 'Removed manually' : 'Added manually';
    refinements.push({
      prompt: `${action}: ${trackHistoryText(track)}`,
      kind,
      applied_at: new Date().toISOString(),
    });
    request.refinements = refinements;
    writeGenerationRequest(request);
  }

  async function waitForExistingAutosave() {
    await new Promise((resolve) => window.setTimeout(resolve, 400));
    const deadline = Date.now() + 3000;
    while (document.body.dataset.librarySaveState === 'saving' && Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    }
  }

  async function ensureLibraryRecord(playlist) {
    if (playlist?.library_id) return playlist.library_id;
    const record = await readJson(await fetch(LIBRARY_ENDPOINT, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: requestBody(playlist),
    }));
    playlist.library_id = record.id;
    if (record.playlist?.tags) playlist.tags = record.playlist.tags;
    writePlaylist(playlist);
    return record.id;
  }

  async function persistPlaylist(playlist, {waitForAutosave = true} = {}) {
    if (waitForAutosave) await waitForExistingAutosave();
    const libraryId = await ensureLibraryRecord(playlist);
    const record = await readJson(await fetch(`${LIBRARY_ENDPOINT}/${encodeURIComponent(libraryId)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: requestBody(playlist),
    }));
    const merged = {...record.playlist, library_id: record.id};
    writePlaylist(merged);
    if (record.generation_request) {
      writeGenerationRequest(record.generation_request);
    }
    return record;
  }

  async function flushPersistence() {
    const playlist = currentPlaylist();
    if (!playlist || !Array.isArray(playlist.tracks)) {
      throw new Error('No editable playlist is available.');
    }
    const record = await persistPlaylist(playlist);
    return record.id;
  }

  function normalized(value) {
    return String(value || '').trim().toLocaleLowerCase().replace(/\s+/g, ' ');
  }

  function identity(track) {
    return `${normalized(track?.artists || track?.artist)}::${normalized(track?.title)}`;
  }

  function duplicateTrack(playlist, track) {
    const videoId = String(track?.video_id || '').trim();
    const trackIdentity = identity(track);
    return playlist.tracks.some((existing) => (
      (videoId && String(existing.video_id || '').trim() === videoId)
      || identity(existing) === trackIdentity
    ));
  }

  async function appendTrack(track) {
    const playlist = currentPlaylist();
    if (!playlist || !Array.isArray(playlist.tracks)) throw new Error('No editable playlist is available.');
    if (playlist.youtube_playlist?.url) throw new Error('Published playlists cannot be edited.');
    if (playlist.tracks.length >= MAX_TRACKS) throw new Error(`A playlist can contain at most ${MAX_TRACKS} tracks.`);
    if (duplicateTrack(playlist, track)) throw new Error('This track is already in the playlist.');

    playlist.tracks.push({
      ...track,
      description: track.description || 'Added manually from YouTube Music.',
      reason: track.reason || 'Added manually to this playlist.',
    });
    playlist.requested_count = playlist.tracks.length;
    playlist.resolved_count = playlist.tracks.length;
    appendManualHistory('manual_add', track);
    writePlaylist(playlist);
    await persistPlaylist(playlist);
    return playlist.tracks.length - 1;
  }

  async function removeTrack(index) {
    const playlist = currentPlaylist();
    if (!playlist || !Array.isArray(playlist.tracks)) throw new Error('No editable playlist is available.');
    if (playlist.youtube_playlist?.url) throw new Error('Published playlists cannot be edited.');
    if (playlist.tracks.length <= 1) throw new Error('A playlist must contain at least one track.');
    if (index < 0 || index >= playlist.tracks.length) throw new Error('The selected track is no longer available.');

    const track = playlist.tracks[index];
    if (!window.confirm(`Remove “${track.title || 'this track'}” from this playlist?`)) return false;

    playlist.tracks.splice(index, 1);
    playlist.requested_count = playlist.tracks.length;
    playlist.resolved_count = playlist.tracks.length;
    appendManualHistory('manual_remove', track);
    writePlaylist(playlist);
    await persistPlaylist(playlist);
    window.location.reload();
    return true;
  }

  function applyRecord(record) {
    if (!record?.id || !record.playlist) return;
    writePlaylist({...record.playlist, library_id: record.id});
    if (record.generation_request) {
      writeGenerationRequest(record.generation_request);
    } else {
      sessionStorage.removeItem(REQUEST_KEY);
    }
    window.location.reload();
  }

  function installDescriptionEditor() {
    if (!descriptionInput) return;
    const playlist = currentPlaylist();
    descriptionInput.value = playlist?.description ?? playlist?.prompt ?? '';
    syncEditorState();

    descriptionInput.addEventListener('input', () => {
      const latest = currentPlaylist();
      if (!latest || !Array.isArray(latest.tracks) || latest.youtube_playlist?.url) return;
      latest.description = descriptionInput.value.slice(0, 2000);
      writePlaylist(latest);
      clearTimeout(descriptionTimer);
      descriptionTimer = window.setTimeout(async () => {
        try {
          await persistPlaylist(currentPlaylist());
        } catch (error) {
          console.warn('Playlist description save failed:', error);
        }
      }, 700);
    });
  }

  function installRemoveActions() {
    if (isPublished()) return;
    document.querySelectorAll('.track[data-track-index]').forEach((item) => {
      if (item.querySelector('.remove-track-button')) return;
      const actions = item.querySelector('.track-actions');
      if (!actions) return;
      const index = Number(item.dataset.trackIndex);
      if (!Number.isInteger(index)) return;

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary track-action remove-track-button';
      button.textContent = 'Remove track';
      button.disabled = currentPlaylist()?.tracks?.length <= 1;
      button.addEventListener('click', async (event) => {
        event.stopPropagation();
        button.disabled = true;
        try {
          await removeTrack(index);
        } catch (error) {
          button.disabled = false;
          window.alert(error.message || String(error));
        }
      });

      const replace = actions.querySelector('.replace-track-button');
      if (replace?.nextSibling) {
        actions.insertBefore(button, replace.nextSibling);
      } else {
        actions.append(button);
      }
    });
  }

  function observeTrackRendering() {
    const list = $('track-list');
    if (!list) return;
    installRemoveActions();
    new MutationObserver(installRemoveActions).observe(list, {childList: true});
  }

  function setStatus(text = '', error = false) {
    const status = host.querySelector('.playlist-add-track-status');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('hidden', !text);
    status.classList.toggle('error', error);
  }

  function renderResults() {
    const container = host.querySelector('.playlist-add-track-results');
    if (!container) return;
    container.replaceChildren();

    if (!results.length) {
      const empty = document.createElement('p');
      empty.className = 'playlist-add-track-empty';
      empty.textContent = 'No matching songs found.';
      container.append(empty);
      return;
    }

    results.forEach((track) => {
      const row = document.createElement('div');
      row.className = 'playlist-add-track-result';

      const image = document.createElement('img');
      image.src = track.thumbnail_url || '';
      image.alt = '';
      image.loading = 'lazy';

      const copy = document.createElement('div');
      copy.className = 'playlist-add-track-copy';
      const title = document.createElement('strong');
      title.textContent = track.title || 'Unknown track';
      const meta = document.createElement('span');
      meta.textContent = [track.artists, track.album, track.duration].filter(Boolean).join(' · ');
      copy.append(title, meta);

      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'secondary playlist-add-track-result-action';
      const duplicate = duplicateTrack(currentPlaylist(), track);
      add.textContent = duplicate ? 'Already added' : 'Add';
      add.disabled = duplicate;
      add.addEventListener('click', async () => {
        const reset = setLoadingButton(add, {label: 'Adding', resetText: 'Add'});
        try {
          await appendTrack(track);
          setStatus(`Added “${track.title}” to the end of the playlist. You can reposition it with the existing reorder controls.`);
          renderResults();
          window.setTimeout(() => window.location.reload(), 450);
        } catch (error) {
          reset();
          setStatus(error.message || String(error), true);
        }
      });

      row.append(image, copy, add);
      container.append(row);
    });
  }

  async function search() {
    const input = host.querySelector('.playlist-add-track-query');
    const button = host.querySelector('.playlist-add-track-search');
    const query = input?.value.trim() || '';
    if (query.length < 2) {
      setStatus('Enter an artist or song title.', true);
      input?.focus();
      return;
    }

    const reset = setLoadingButton(button, {label: 'Searching', resetText: 'Search'});
    setStatus('Searching YouTube Music…');
    try {
      const payload = await readJson(
        await fetch(`${SEARCH_ENDPOINT}?q=${encodeURIComponent(query)}&limit=${SEARCH_LIMIT}`),
        {flattenValidationErrors: true},
      );
      results = Array.isArray(payload.results) ? payload.results : [];
      renderResults();
      setStatus(results.length ? '' : 'No matching songs found.', !results.length);
    } catch (error) {
      results = [];
      renderResults();
      setStatus(error.message || String(error), true);
    } finally {
      reset();
    }
  }

  function closePanel() {
    host.replaceChildren();
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus();
    results = [];
  }

  function openPanel() {
    if (host.firstElementChild) {
      closePanel();
      return;
    }
    if (isPublished()) return;

    const panel = document.createElement('section');
    panel.className = 'playlist-add-track-panel';
    panel.setAttribute('aria-label', 'Add a track');

    const head = document.createElement('div');
    head.className = 'playlist-editor-panel-head';
    const heading = document.createElement('strong');
    heading.textContent = 'Add a track';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'secondary playlist-editor-close';
    close.textContent = 'Close';
    close.addEventListener('click', closePanel);
    head.append(heading, close);

    const searchRow = document.createElement('div');
    searchRow.className = 'playlist-add-track-search-row';
    const input = document.createElement('input');
    input.type = 'search';
    input.className = 'playlist-add-track-query';
    input.placeholder = 'Song title or artist';
    input.autocomplete = 'off';
    input.maxLength = 300;
    input.setAttribute('aria-label', 'Song title or artist');
    const searchButton = document.createElement('button');
    searchButton.type = 'button';
    searchButton.className = 'primary playlist-add-track-search';
    searchButton.textContent = 'Search';
    searchButton.addEventListener('click', () => void search());
    input.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      void search();
    });
    searchRow.append(input, searchButton);

    const status = document.createElement('p');
    status.className = 'playlist-add-track-status hidden';
    status.setAttribute('aria-live', 'polite');
    const resultContainer = document.createElement('div');
    resultContainer.className = 'playlist-add-track-results';

    panel.append(head, searchRow, status, resultContainer);
    host.append(panel);
    trigger.setAttribute('aria-expanded', 'true');
    input.focus();
  }

  trigger.setAttribute('aria-expanded', 'false');
  trigger.addEventListener('click', openPanel);
  installDescriptionEditor();
  observeTrackRendering();
  window.addEventListener('playlistmuse-playlist-published', syncEditorState);

  window.PlaylistMusePlaylistEditor = {
    appendTrack,
    applyRecord,
    flushPersistence,
    isPublished,
    removeTrack,
    syncEditorState,
  };
})();
