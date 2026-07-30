(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const ARTWORK_ENDPOINT = '/api/artwork/track';
  const $ = (id) => document.getElementById(id);
  let expandedIndex = null;

  function readStoredJson(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || 'null');
    } catch {
      return null;
    }
  }

  function savePlaylist() {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
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

  function trackArtworkUrl(track) {
    return track.album_artwork_url || track.thumbnail_url || '';
  }

  function representativeIndexes(length) {
    if (!length) return [];
    const last = length - 1;
    return [...new Set([
      0,
      Math.round(last / 3),
      Math.round((last * 2) / 3),
      last,
    ])];
  }

  function playlistCoverUrls() {
    const urls = [];
    const add = (track) => {
      const url = trackArtworkUrl(track);
      if (url && !urls.includes(url)) urls.push(url);
    };

    representativeIndexes(data.tracks.length).forEach((index) => add(data.tracks[index]));
    data.tracks.forEach(add);
    return urls.slice(0, 4);
  }

  function renderPlaylistCover() {
    const container = $('playlist-cover-grid');
    const urls = playlistCoverUrls();
    const tiles = [];

    for (let index = 0; index < 4; index += 1) {
      const url = urls[index];
      if (url) {
        const image = document.createElement('img');
        image.src = url;
        image.alt = '';
        image.loading = index === 0 ? 'eager' : 'lazy';
        tiles.push(image);
      } else {
        const placeholder = document.createElement('span');
        placeholder.className = 'playlist-cover-placeholder';
        tiles.push(placeholder);
      }
    }

    container.replaceChildren(...tiles);
    const musicBrainzCount = data.tracks.filter(
      (track) => track.artwork_source === 'musicbrainz',
    ).length;
    $('playlist-cover-status').textContent = musicBrainzCount
      ? `Playlist cover updated with ${Math.min(musicBrainzCount, 4)} album artworks.`
      : 'Playlist cover created from YouTube Music thumbnails.';
  }

  function updateTrackArtwork(index) {
    const image = document.querySelector(
      `.track[data-track-index="${index}"] .track-artwork`,
    );
    const track = data.tracks[index];
    const url = track ? trackArtworkUrl(track) : '';
    if (image && url) image.src = url;
  }

  async function enrichTrackArtwork(index) {
    const track = data.tracks[index];
    if (!track || track.artwork_checked) return;

    if (!track.title || !track.artists || !track.album) {
      track.artwork_checked = true;
      track.artwork_source = 'youtube';
      savePlaylist();
      return;
    }

    try {
      const payload = await readJson(await fetch(ARTWORK_ENDPOINT, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          title: track.title,
          artists: track.artists,
          album: track.album,
          thumbnail_url: track.thumbnail_url || null,
        }),
      }));

      track.artwork_checked = true;
      track.artwork_source = payload.source || 'youtube';
      if (payload.source === 'musicbrainz' && payload.artwork_url) {
        track.album_artwork_url = payload.artwork_url;
        track.release_group_mbid = payload.release_group_mbid || null;
        track.release_group_title = payload.release_group_title || null;
      }
      savePlaylist();
      updateTrackArtwork(index);
      renderPlaylistCover();
    } catch (error) {
      console.debug('Album artwork enrichment skipped:', error);
    }
  }

  async function enrichArtwork() {
    const priority = representativeIndexes(data.tracks.length);
    const remaining = data.tracks
      .map((_, index) => index)
      .filter((index) => !priority.includes(index));

    for (const index of [...priority, ...remaining]) {
      await enrichTrackArtwork(index);
    }
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

  function setReplacingButton(button) {
    const spinner = document.createElement('span');
    spinner.className = 'generation-spinner';
    spinner.setAttribute('aria-hidden', 'true');

    const label = document.createElement('span');
    label.className = 'generation-label';
    label.textContent = 'Replacing';

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
      button.textContent = 'Replace track';
    };
  }

  async function replaceTrack(index, button, status) {
    const currentTrack = data.tracks[index];
    const resetReplacingButton = setReplacingButton(button);
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
      savePlaylist();
      renderPlaylist();
      void enrichTrackArtwork(index);
    } catch (error) {
      status.textContent = error.message || String(error);
      status.classList.add('error');
      resetReplacingButton();
    }
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

    const artwork = document.createElement('img');
    artwork.className = 'track-artwork';
    artwork.loading = 'lazy';
    artwork.alt = `Album artwork for ${track.title || 'track'}`;
    const artworkUrl = trackArtworkUrl(track);
    if (artworkUrl) artwork.src = artworkUrl;

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

    actions.append(play, replace);
    detailsInner.append(explanation, actions, replaceStatus);
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

  const data = readStoredJson(STORAGE_KEY);
  const generationRequest = readStoredJson(REQUEST_KEY);

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

  renderPlaylist();
  void enrichArtwork();
})();
