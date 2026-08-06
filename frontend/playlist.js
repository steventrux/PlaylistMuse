(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const LIBRARY_ENDPOINT = '/api/library/playlists';
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;
  let expandedIndex = null;
  let persistenceTimer = null;
  let createRecordPromise = null;
  let localRevision = 0;

  function readStoredJson(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || 'null');
    } catch {
      return null;
    }
  }

  let data = readStoredJson(STORAGE_KEY);
  let generationRequest = readStoredJson(REQUEST_KEY);
  const requestedLibraryId = new URLSearchParams(window.location.search).get('id');

  function writeSessionPlaylist() {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  }

  function playlistDocument() {
    const playlist = JSON.parse(JSON.stringify(data));
    delete playlist.library_id;
    return playlist;
  }

  function libraryRequestBody() {
    return JSON.stringify({
      playlist: playlistDocument(),
      generation_request: generationRequest || null,
    });
  }

  async function persistLibraryRecord(revision = localRevision) {
    if (!data?.library_id) return;
    try {
      await readJson(await fetch(`${LIBRARY_ENDPOINT}/${encodeURIComponent(data.library_id)}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: libraryRequestBody(),
        keepalive: true,
      }));
      if (revision === localRevision) document.body.dataset.librarySaveState = 'saved';
    } catch (error) {
      document.body.dataset.librarySaveState = 'error';
      console.warn('Playlist library save failed:', error);
    }
  }

  function schedulePersistence({immediate = false} = {}) {
    if (!data?.library_id) {
      void ensureLibraryRecord();
      return;
    }
    localRevision += 1;
    document.body.dataset.librarySaveState = 'saving';
    clearTimeout(persistenceTimer);
    const revision = localRevision;
    if (immediate) {
      void persistLibraryRecord(revision);
      return;
    }
    persistenceTimer = window.setTimeout(() => {
      void persistLibraryRecord(revision);
    }, 350);
  }

  function savePlaylist(options = {}) {
    writeSessionPlaylist();
    schedulePersistence(options);
  }

  async function ensureLibraryRecord() {
    if (!data || !Array.isArray(data.tracks) || data.library_id) return data?.library_id || null;
    if (createRecordPromise) return createRecordPromise;

    document.body.dataset.librarySaveState = 'saving';
    createRecordPromise = (async () => {
      const record = await readJson(await fetch(LIBRARY_ENDPOINT, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: libraryRequestBody(),
      }));
      data.library_id = record.id;
      writeSessionPlaylist();
      document.body.dataset.librarySaveState = 'saved';
      await persistLibraryRecord(localRevision);
      return record.id;
    })().catch((error) => {
      document.body.dataset.librarySaveState = 'error';
      console.warn('Playlist library migration failed:', error);
      return null;
    }).finally(() => {
      createRecordPromise = null;
    });

    return createRecordPromise;
  }

  async function loadRequestedPlaylist() {
    try {
      const record = await readJson(await fetch(
        `${LIBRARY_ENDPOINT}/${encodeURIComponent(requestedLibraryId)}`,
        {cache: 'no-store'},
      ));
      data = {...record.playlist, library_id: record.id};
      generationRequest = record.generation_request || null;
      writeSessionPlaylist();
      if (generationRequest) {
        sessionStorage.setItem(REQUEST_KEY, JSON.stringify(generationRequest));
      } else {
        sessionStorage.removeItem(REQUEST_KEY);
      }
      window.location.replace('/static/playlist.html');
    } catch (error) {
      $('empty-state').textContent = error.message || 'The requested playlist could not be opened.';
      $('empty-state').classList.remove('hidden');
      $('playlist-summary').textContent = '';
    }
  }

  function ensureLibraryLink() {
    const toolbar = document.querySelector('.playlist-toolbar');
    if (!toolbar || toolbar.querySelector('[data-library-link]')) return;
    const link = document.createElement('a');
    link.href = '/static/library.html';
    link.className = 'back-link';
    link.dataset.libraryLink = 'true';
    link.textContent = 'My playlists';
    toolbar.append(link);
  }

  function isPublished() {
    return Boolean(data.youtube_playlist?.url);
  }

  function durationToSeconds(value) {
    if (!value) return 0;
    const parts = String(value).trim().split(':').map(Number);
    if (!parts.length || parts.some((part) => !Number.isFinite(part) || part < 0)) return 0;
    return parts.reduce((total, part) => (total * 60) + part, 0);
  }

  function formatPlaylistDuration(totalSeconds) {
    if (!totalSeconds) return '';
    let totalMinutes = Math.round(totalSeconds / 60);
    const hours = Math.floor(totalMinutes / 60);
    totalMinutes %= 60;
    if (hours && totalMinutes) return `${hours} h ${totalMinutes} min`;
    if (hours) return `${hours} h`;
    return `${totalMinutes} min`;
  }

  function updateSummary() {
    const totalSeconds = data.tracks.reduce(
      (total, track) => total + durationToSeconds(track.duration),
      0,
    );
    const durationText = formatPlaylistDuration(totalSeconds);
    const trackLabel = `${data.tracks.length} ${data.tracks.length === 1 ? 'track' : 'tracks'}`;
    $('playlist-summary').textContent = durationText ? `${trackLabel} · ${durationText}` : trackLabel;
  }

  function coverPlaceholder() {
    const placeholder = document.createElement('span');
    placeholder.className = 'playlist-cover-placeholder';
    return placeholder;
  }

  function renderPlaylistCover() {
    const mosaic = window.PlaylistMuseMosaic;
    const tileCount = mosaic?.TILE_COUNT || 4;
    const urls = mosaic?.selectMosaicUrls(data.tracks) || [];
    const tiles = [];

    for (let index = 0; index < tileCount; index += 1) {
      const url = urls[index];
      if (!url) {
        tiles.push(coverPlaceholder());
        continue;
      }

      const image = document.createElement('img');
      image.src = url;
      image.alt = '';
      image.loading = 'eager';
      image.decoding = 'async';
      image.fetchPriority = index === 0 ? 'high' : 'auto';
      image.addEventListener('error', () => {
        image.replaceWith(coverPlaceholder());
      }, {once: true});
      tiles.push(image);
    }

    $('playlist-cover-grid').replaceChildren(...tiles);
  }

  function detailBlock(title, text) {
    const block = document.createElement('section');
    block.className = 'track-detail-block';

    const heading = document.createElement('h3');
    heading.textContent = title;

    const paragraph = document.createElement('p');
    paragraph.textContent = text;

    block.append(heading, paragraph);
    return block;
  }

  function closeOtherTracks(currentItem) {
    document.querySelectorAll('.track.expanded').forEach((item) => {
      if (item === currentItem) return;
      item.classList.remove('expanded');
      item.setAttribute('aria-expanded', 'false');
    });
  }

  function toggleTrack(item, index) {
    const willExpand = !item.classList.contains('expanded');
    closeOtherTracks(item);
    item.classList.toggle('expanded', willExpand);
    item.setAttribute('aria-expanded', String(willExpand));
    expandedIndex = willExpand ? index : null;
    if (willExpand) {
      item.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }
  }

  function replacementOptions() {
    return generationRequest?.options || {
      exclude_live: true,
      exclude_covers: true,
      exclude_remixes: true,
    };
  }

  async function replaceTrack(index, button, status) {
    const currentTrack = data.tracks[index];
    const resetReplacingButton = setLoadingButton(button, {
      label: 'Replacing',
      resetText: 'Replace track',
    });
    status.textContent = 'Finding a new track that preserves this song’s role…';
    status.classList.remove('error');

    const request = {
      prompt: data.prompt || 'Create a cohesive playlist matching the current selection.',
      playlist_name: data.name || '',
      playlist_description: data.description || '',
      current_track: {
        video_id: currentTrack.video_id || null,
        title: currentTrack.title || 'Unknown track',
        artists: currentTrack.artists || 'Unknown artist',
        description: currentTrack.description || '',
        reason: currentTrack.reason || '',
      },
      existing_tracks: data.tracks.map((track) => ({
        video_id: track.video_id || null,
        title: track.title || 'Unknown track',
        artists: track.artists || 'Unknown artist',
        description: track.description || '',
        reason: track.reason || '',
      })),
      options: replacementOptions(),
    };

    try {
      const payload = await readJson(await fetch('/api/playlists/replace-track', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(request),
      }));

      data.tracks[index] = payload.track;
      data.resolved_count = data.tracks.length;
      expandedIndex = index;
      savePlaylist({immediate: true});
      renderPlaylist();
    } catch (error) {
      status.textContent = error.message || String(error);
      status.classList.add('error');
      resetReplacingButton();
    }
  }

  function renderTrack(track, index) {
    const item = document.createElement('li');
    item.className = 'track track-result-card';
    item.tabIndex = 0;
    item.setAttribute('role', 'button');
    item.setAttribute('aria-expanded', String(expandedIndex === index));
    item.setAttribute('aria-label', `Show details for ${track.title || 'this track'}`);
    if (expandedIndex === index) item.classList.add('expanded');

    const artwork = document.createElement('img');
    artwork.className = 'track-artwork';
    artwork.loading = 'lazy';
    artwork.alt = `Cover artwork for ${track.title || 'track'}`;
    artwork.src = track.thumbnail_url || '';

    const copy = document.createElement('div');
    copy.className = 'track-copy';

    const heading = document.createElement('strong');
    heading.className = 'track-heading';

    const titleText = document.createElement('span');
    titleText.className = 'track-title';
    titleText.textContent = `${index + 1}. ${track.title || 'Unknown track'}`;
    heading.append(titleText);

    if (track.duration) {
      const duration = document.createElement('span');
      duration.className = 'track-duration';
      duration.textContent = ` - ${track.duration}`;
      heading.append(duration);
    }

    heading.title = `${index + 1}. ${track.title || 'Unknown track'}${track.duration ? ` - ${track.duration}` : ''}`;

    const meta = document.createElement('span');
    meta.className = 'track-meta';
    meta.textContent = [track.artists, track.album].filter(Boolean).join(' · ');
    meta.title = meta.textContent;
    copy.append(heading, meta);

    const expandIcon = document.createElement('span');
    expandIcon.className = 'track-expand-icon';
    expandIcon.setAttribute('aria-hidden', 'true');
    expandIcon.innerHTML = '<svg viewBox="0 0 24 24" focusable="false"><path d="m7 10 5 5 5-5"/></svg>';

    const details = document.createElement('div');
    details.className = 'track-details';
    const detailsInner = document.createElement('div');
    detailsInner.className = 'track-details-inner';

    const explanation = document.createElement('div');
    explanation.className = 'track-explanation';
    explanation.append(
      detailBlock(
        'About this track',
        track.description || 'Detailed notes are not available because this playlist was generated before track explanations were introduced.',
      ),
      detailBlock(
        'Why it belongs here',
        track.reason || 'The role of this track was not stored with this earlier playlist generation.',
      ),
    );
    const actions = document.createElement('div');
    actions.className = 'track-actions';

    const play = document.createElement('a');
    play.className = 'primary track-action';
    play.href = track.url || `https://music.youtube.com/watch?v=${encodeURIComponent(track.video_id || '')}`;
    play.target = '_blank';
    play.rel = 'noopener noreferrer';
    play.textContent = 'Open in YouTube Music';
    play.addEventListener('click', (event) => event.stopPropagation());
    actions.append(play);

    detailsInner.append(explanation, actions);

    if (!isPublished()) {
      const replace = document.createElement('button');
      replace.type = 'button';
      replace.className = 'secondary track-action replace-track-button';
      replace.textContent = 'Replace track';

      const replaceStatus = document.createElement('p');
      replaceStatus.className = 'track-replace-status';
      replaceStatus.setAttribute('aria-live', 'polite');

      replace.addEventListener('click', (event) => {
        event.stopPropagation();
        replaceTrack(index, replace, replaceStatus);
      });

      actions.append(replace);
      detailsInner.append(replaceStatus);
    }

    details.append(detailsInner);

    item.append(artwork, copy, expandIcon, details);
    item.addEventListener('click', (event) => {
      if (event.target.closest('a, button')) return;
      toggleTrack(item, index);
    });
    item.addEventListener('keydown', (event) => {
      if (event.target !== item || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      toggleTrack(item, index);
    });

    return item;
  }

  function renderPlaylist() {
    updateSummary();
    $('playlist-description').textContent = data.description || data.prompt || '';
    $('track-list').replaceChildren(...data.tracks.map(renderTrack));
    renderPlaylistCover();
  }

  ensureLibraryLink();

  if (requestedLibraryId && data?.library_id !== requestedLibraryId) {
    $('playlist-summary').textContent = 'Loading playlist…';
    void loadRequestedPlaylist();
    return;
  }
  if (requestedLibraryId) {
    window.history.replaceState(null, '', '/static/playlist.html');
  }

  if (!data || !Array.isArray(data.tracks)) {
    $('empty-state').classList.remove('hidden');
    $('playlist-summary').textContent = '';
    return;
  }

  const titleInput = $('playlist-name');
  titleInput.value = data.name || 'Generated playlist';
  titleInput.addEventListener('input', () => {
    data.name = titleInput.value.slice(0, 100);
    savePlaylist();
  });
  titleInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      titleInput.blur();
    }
  });

  window.addEventListener('playlistmuse-playlist-published', (event) => {
    const result = event.detail;
    if (!result?.url) return;
    data.youtube_playlist = result;
    expandedIndex = null;
    savePlaylist({immediate: true});
    renderPlaylist();
  });

  window.addEventListener('pagehide', () => {
    if (data?.library_id && document.body.dataset.librarySaveState === 'saving') {
      void persistLibraryRecord(localRevision);
    }
  });

  renderPlaylist();
  void ensureLibraryRecord();
})();
