(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const LIBRARY_ENDPOINT = '/api/library/playlists';
  const FAVORITES_ENDPOINT = '/api/favorites';
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;
  const tagTools = window.PlaylistMuseTags || window.PlaylistMuseLibraryTags;
  let favoriteTrackIds = new Set();
  let favoriteArtistKeys = new Set();
  let expandedIndex = null;
  let draggedIndex = null;
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
    // Never resend a cached tags snapshot here: it can predate the AI tag
    // suggestion that runs in the background right after creation, and would
    // silently overwrite it. The server preserves existing tags whenever the
    // field is absent from an update; tag edits go through persistPlaylistTags,
    // which fetches the latest record first instead of relying on this snapshot.
    delete playlist.tags;
    // Client-only session markers -- must never reach a persisted library record.
    delete playlist.playlistmuseFreshlyGenerated;
    delete playlist.playlistmuseTasteCaptured;
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
      if (record.playlist?.tags) data.tags = record.playlist.tags;
      writeSessionPlaylist();
      renderPlaylistTags();
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

  function setPlaylistTagStatus(text = '', error = false) {
    const status = $('playlist-tags-status');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('hidden', !text);
    status.classList.toggle('error', error);
  }

  async function persistPlaylistTags(nextTags) {
    const libraryId = await ensureLibraryRecord();
    if (!libraryId) throw new Error('Playlist tags could not be saved.');

    const record = await readJson(await fetch(
      `${LIBRARY_ENDPOINT}/${encodeURIComponent(libraryId)}`,
      {cache: 'no-store'},
    ));
    const latestTags = tagTools.normalize(record.playlist?.tags);
    const requestedTags = tagTools.normalize(nextTags);
    latestTags.custom = requestedTags.custom;
    record.playlist.tags = latestTags;

    const updated = await readJson(await fetch(
      `${LIBRARY_ENDPOINT}/${encodeURIComponent(libraryId)}`,
      {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          playlist: record.playlist,
          generation_request: record.generation_request || null,
        }),
      },
    ));
    data.tags = updated.playlist?.tags || latestTags;
    writeSessionPlaylist();
    renderPlaylistTags();
  }

  async function regeneratePlaylistTags() {
    const libraryId = await ensureLibraryRecord();
    if (!libraryId) throw new Error('Playlist tags could not be regenerated.');

    const updated = await readJson(await fetch(
      `${LIBRARY_ENDPOINT}/${encodeURIComponent(libraryId)}/tags/suggest`,
      {method: 'POST'},
    ));
    data.tags = updated.playlist?.tags || data.tags;
    writeSessionPlaylist();
    renderPlaylistTags();
  }

  function hasAiTags(tags) {
    const normalized = tagTools.normalize(tags);
    return Boolean(normalized.genre.length || normalized.mood.length || normalized.period.length);
  }

  function renderPlaylistTags() {
    const container = $('playlist-tags');
    if (!container || !tagTools) return;
    // Regenerating would silently replace a human's own edits, so only offer it
    // for an untagged draft -- once tags exist, or the playlist is published,
    // the only way to change them is the explicit add/remove personal-tag controls.
    const canRegenerate = !isPublished() && !hasAiTags(data?.tags);
    container.replaceChildren(tagTools.editableSummary(data?.tags, {
      onAddPersonal: async (value) => {
        setPlaylistTagStatus('Adding personal tag…');
        const nextTags = tagTools.addPersonal(data?.tags, value);
        await persistPlaylistTags(nextTags);
        setPlaylistTagStatus('');
      },
      onRemovePersonal: async (value) => {
        setPlaylistTagStatus('Removing personal tag…');
        const nextTags = tagTools.removePersonal(data?.tags, value);
        await persistPlaylistTags(nextTags);
        setPlaylistTagStatus('');
      },
      onRegenerate: canRegenerate ? async () => {
        setPlaylistTagStatus('Regenerating AI tags…');
        await regeneratePlaylistTags();
        setPlaylistTagStatus('');
      } : undefined,
      onError: (error) => setPlaylistTagStatus(error.message || String(error), true),
    }));
  }

  async function refreshPlaylistTagsFromLibrary() {
    if (!data?.library_id) {
      await ensureLibraryRecord();
      return;
    }
    try {
      const record = await readJson(await fetch(
        `${LIBRARY_ENDPOINT}/${encodeURIComponent(data.library_id)}`,
        {cache: 'no-store'},
      ));
      if (record.playlist?.tags) {
        data.tags = record.playlist.tags;
        writeSessionPlaylist();
        renderPlaylistTags();
      }
    } catch (error) {
      console.warn('Playlist tags could not be refreshed:', error);
    }
  }

  async function loadFavorites() {
    try {
      const payload = await readJson(await fetch(FAVORITES_ENDPOINT, {cache: 'no-store'}));
      favoriteTrackIds = new Set((payload.tracks || []).map((track) => track.video_id));
      favoriteArtistKeys = new Set((payload.artists || []).map((artist) => (artist.name || '').toLocaleLowerCase()));
      renderPlaylist();
    } catch (error) {
      console.warn('Favorites could not be loaded:', error);
    }
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

  function clearDragState() {
    draggedIndex = null;
    document.querySelectorAll('.track-result-card.dragging, .track-result-card.drag-over')
      .forEach((item) => item.classList.remove('dragging', 'drag-over'));
  }

  function moveTrack(fromIndex, toIndex) {
    if (
      isPublished()
      || fromIndex === toIndex
      || fromIndex < 0
      || toIndex < 0
      || fromIndex >= data.tracks.length
      || toIndex >= data.tracks.length
    ) {
      return;
    }

    const [track] = data.tracks.splice(fromIndex, 1);
    data.tracks.splice(toIndex, 0, track);
    data.resolved_count = data.tracks.length;
    expandedIndex = expandedIndex === fromIndex ? toIndex : null;
    savePlaylist({immediate: true});
    renderPlaylist();

    const moved = document.querySelector(`[data-track-index="${toIndex}"]`);
    moved?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
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

  function createMoveButton(label, index, targetIndex, disabled) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary track-action track-move-button';
    button.textContent = label;
    button.disabled = disabled;
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      moveTrack(index, targetIndex);
    });
    return button;
  }

  function createReorderHandle(item, track, index) {
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'track-reorder-handle';
    handle.draggable = true;
    handle.title = 'Drag to reorder';
    handle.setAttribute('aria-label', `Drag ${track.title || 'this track'} to reorder`);
    handle.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="8" cy="6" r="1.5"/><circle cx="16" cy="6" r="1.5"/>
        <circle cx="8" cy="12" r="1.5"/><circle cx="16" cy="12" r="1.5"/>
        <circle cx="8" cy="18" r="1.5"/><circle cx="16" cy="18" r="1.5"/>
      </svg>
    `;

    handle.addEventListener('click', (event) => event.stopPropagation());
    handle.addEventListener('dragstart', (event) => {
      event.stopPropagation();
      draggedIndex = index;
      item.classList.add('dragging');
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(index));
      }
    });
    handle.addEventListener('dragend', clearDragState);
    return handle;
  }

  // Menu panels are portaled to <body> with position:fixed (positioned via JS
  // on open) instead of living inside the track card: the card and its
  // details pane use overflow:hidden to drive the expand/collapse animation,
  // which would silently clip an absolutely-positioned dropdown to nothing.
  const favoriteMenuToggles = new WeakMap();

  function closeFavoriteTrackMenus() {
    document.querySelectorAll('.favorite-track-menu-panel:not(.hidden)').forEach((panel) => {
      panel.classList.add('hidden');
      favoriteMenuToggles.get(panel)?.setAttribute('aria-expanded', 'false');
    });
  }

  function removeFavoriteTrackMenuPortals() {
    document.querySelectorAll('.favorite-track-menu-panel').forEach((panel) => panel.remove());
  }

  function positionFavoriteTrackMenu(toggle, menu) {
    const rect = toggle.getBoundingClientRect();
    menu.style.top = `${Math.round(rect.bottom + 6)}px`;
    const left = Math.min(
      Math.max(8, rect.right - menu.offsetWidth),
      window.innerWidth - menu.offsetWidth - 8,
    );
    menu.style.left = `${Math.round(left)}px`;
  }

  function buildFavoriteTrackMenu(track) {
    const wrap = document.createElement('div');
    wrap.className = 'favorite-track-menu';

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'secondary track-action favorite-track-button';
    toggle.setAttribute('aria-haspopup', 'true');

    const menu = document.createElement('div');
    menu.className = 'favorite-track-menu-panel hidden';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Add to favorites');
    favoriteMenuToggles.set(menu, toggle);

    const trackOption = document.createElement('button');
    trackOption.type = 'button';
    trackOption.className = 'favorite-track-option';
    trackOption.dataset.target = 'track';
    trackOption.setAttribute('role', 'menuitem');
    menu.append(trackOption);

    const artistName = (track.artists || '').trim();
    const artistOption = document.createElement('button');
    if (artistName) {
      artistOption.type = 'button';
      artistOption.className = 'favorite-track-option';
      artistOption.dataset.target = 'artist';
      artistOption.setAttribute('role', 'menuitem');
      menu.append(artistOption);
    }

    wrap.append(toggle);

    const isTrackFavorited = () => favoriteTrackIds.has(track.video_id);
    const isArtistFavorited = () => favoriteArtistKeys.has(artistName.toLocaleLowerCase());

    const applyState = () => {
      window.PlaylistMuseActionControls?.decorateFavoriteToggle(
        toggle,
        {trackFavorited: isTrackFavorited(), artistFavorited: isArtistFavorited()},
      );
      toggle.removeAttribute('aria-pressed');
      toggle.setAttribute('aria-expanded', String(!menu.classList.contains('hidden')));

      trackOption.textContent = isTrackFavorited() ? 'Remove track from favorites' : 'Add track to favorites';
      trackOption.classList.toggle('is-favorited', isTrackFavorited());
      if (artistName) {
        artistOption.textContent = isArtistFavorited() ? 'Remove artist from favorites' : 'Add artist to favorites';
        artistOption.classList.toggle('is-favorited', isArtistFavorited());
      }
    };
    applyState();

    toggle.addEventListener('click', (event) => {
      event.stopPropagation();
      const isOpen = !menu.classList.contains('hidden');
      closeFavoriteTrackMenus();
      if (!isOpen) {
        document.body.append(menu);
        menu.classList.remove('hidden');
        positionFavoriteTrackMenu(toggle, menu);
        toggle.setAttribute('aria-expanded', 'true');
      }
    });

    async function toggleFavoriteTrack() {
      if (isTrackFavorited()) {
        await readJson(await fetch(
          `${FAVORITES_ENDPOINT}/tracks/${encodeURIComponent(track.video_id)}`,
          {method: 'DELETE'},
        ));
        favoriteTrackIds.delete(track.video_id);
      } else {
        await readJson(await fetch(`${FAVORITES_ENDPOINT}/tracks`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            video_id: track.video_id,
            title: track.title || '',
            artists: track.artists || '',
            album: track.album || '',
            thumbnail_url: track.thumbnail_url || '',
          }),
        }));
        favoriteTrackIds.add(track.video_id);
      }
    }

    async function toggleFavoriteArtist() {
      const key = artistName.toLocaleLowerCase();
      if (isArtistFavorited()) {
        await readJson(await fetch(
          `${FAVORITES_ENDPOINT}/artists?name=${encodeURIComponent(artistName)}`,
          {method: 'DELETE'},
        ));
        favoriteArtistKeys.delete(key);
      } else {
        await readJson(await fetch(`${FAVORITES_ENDPOINT}/artists`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: artistName}),
        }));
        favoriteArtistKeys.add(key);
      }
    }

    menu.addEventListener('click', async (event) => {
      event.stopPropagation();
      const option = event.target.closest('.favorite-track-option');
      if (!option) return;
      option.disabled = true;
      try {
        if (option.dataset.target === 'track') {
          await toggleFavoriteTrack();
        } else {
          await toggleFavoriteArtist();
        }
        applyState();
      } catch (error) {
        window.alert(error.message || String(error));
      } finally {
        option.disabled = false;
        closeFavoriteTrackMenus();
      }
    });

    return wrap;
  }

  function renderTrack(track, index) {
    const item = document.createElement('li');
    item.className = 'track track-result-card';
    item.dataset.trackIndex = String(index);
    item.tabIndex = 0;
    item.setAttribute('role', 'button');
    item.setAttribute('aria-expanded', String(expandedIndex === index));
    item.setAttribute('aria-label', `Show details for ${track.title || 'this track'}`);
    if (expandedIndex === index) item.classList.add('expanded');

    const canReorder = !isPublished();
    if (canReorder) item.classList.add('reorderable');

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

    if (track.video_id) {
      actions.append(buildFavoriteTrackMenu(track));
    }

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

      actions.append(
        replace,
        createMoveButton('Move up', index, index - 1, index === 0),
        createMoveButton('Move down', index, index + 1, index === data.tracks.length - 1),
      );
      detailsInner.append(replaceStatus);
    }

    details.append(detailsInner);

    item.append(artwork, copy);
    if (canReorder) item.append(createReorderHandle(item, track, index));
    item.append(expandIcon, details);

    if (canReorder) {
      item.addEventListener('dragover', (event) => {
        if (draggedIndex === null || draggedIndex === index) return;
        event.preventDefault();
        item.classList.add('drag-over');
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      });
      item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
      item.addEventListener('drop', (event) => {
        if (draggedIndex === null) return;
        event.preventDefault();
        const fromIndex = draggedIndex;
        clearDragState();
        moveTrack(fromIndex, index);
      });
    }

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
    renderPlaylistTags();
    removeFavoriteTrackMenuPortals();
    $('track-list').replaceChildren(...data.tracks.map(renderTrack));
    renderPlaylistCover();
  }

  function trackUrl(track) {
    return track.url || (track.video_id
      ? `https://music.youtube.com/watch?v=${encodeURIComponent(track.video_id)}`
      : '');
  }

  function sanitizeFilename(name) {
    const cleaned = String(name || '').replace(/[\\/:*?"<>|]+/g, '_').trim();
    return cleaned || 'playlist';
  }

  function triggerDownload(filename, content, mimeType) {
    const blob = new Blob([content], {type: mimeType});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function buildM3uPlaylist() {
    const lines = ['#EXTM3U'];
    if (data.name) lines.push(`#PLAYLIST:${data.name}`);
    data.tracks.forEach((track) => {
      const seconds = durationToSeconds(track.duration) || -1;
      const label = [track.artists, track.title].filter(Boolean).join(' - ') || 'Unknown track';
      lines.push(`#EXTINF:${seconds},${label}`);
      lines.push(trackUrl(track));
    });
    return `${lines.join('\n')}\n`;
  }

  function csvField(value) {
    const text = String(value ?? '');
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function buildCsvPlaylist() {
    const rows = [['#', 'Title', 'Artists', 'Album', 'Duration', 'URL'].map(csvField).join(',')];
    data.tracks.forEach((track, index) => {
      rows.push([
        index + 1,
        track.title || '',
        track.artists || '',
        track.album || '',
        track.duration || '',
        trackUrl(track),
      ].map(csvField).join(','));
    });
    return '﻿' + rows.join('\r\n') + '\r\n';
  }

  function exportPlaylist(format) {
    if (!data?.tracks?.length) return;
    const filenameBase = sanitizeFilename(data.name);
    if (format === 'csv') {
      triggerDownload(`${filenameBase}.csv`, buildCsvPlaylist(), 'text/csv;charset=utf-8');
    } else {
      triggerDownload(`${filenameBase}.m3u8`, buildM3uPlaylist(), 'audio/x-mpegurl;charset=utf-8');
    }
  }

  function initExportControls() {
    const toggle = $('export-playlist');
    const menu = $('export-playlist-menu');
    if (!toggle || !menu) return;

    const closeMenu = () => {
      menu.classList.add('hidden');
      toggle.setAttribute('aria-expanded', 'false');
    };

    toggle.addEventListener('click', (event) => {
      event.stopPropagation();
      const isOpen = !menu.classList.contains('hidden');
      if (isOpen) {
        closeMenu();
      } else {
        menu.classList.remove('hidden');
        toggle.setAttribute('aria-expanded', 'true');
      }
    });

    menu.addEventListener('click', (event) => {
      const option = event.target.closest('.playlist-export-option');
      if (!option) return;
      exportPlaylist(option.dataset.format);
      closeMenu();
    });

    document.addEventListener('click', (event) => {
      if (!menu.classList.contains('hidden') && !event.target.closest('.playlist-export-menu')) {
        closeMenu();
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !menu.classList.contains('hidden')) closeMenu();
    });
  }

  document.addEventListener('click', (event) => {
    if (!event.target.closest('.favorite-track-menu')) closeFavoriteTrackMenus();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeFavoriteTrackMenus();
  });

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
    clearDragState();
    savePlaylist({immediate: true});
    renderPlaylist();
  });

  window.addEventListener('pagehide', () => {
    if (data?.library_id && document.body.dataset.librarySaveState === 'saving') {
      void persistLibraryRecord(localRevision);
    }
  });

  renderPlaylist();
  initExportControls();
  void refreshPlaylistTagsFromLibrary();
  void loadFavorites();
})();
