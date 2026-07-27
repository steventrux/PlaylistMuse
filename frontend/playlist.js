(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const $ = (id) => document.getElementById(id);

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

  function renderTrack(track, index) {
    const item = document.createElement('li');
    item.className = 'track';

    const artwork = document.createElement('img');
    artwork.loading = 'lazy';
    artwork.alt = '';
    artwork.src = track.thumbnail_url || '';

    const copy = document.createElement('div');
    copy.className = 'track-copy';

    const heading = document.createElement('div');
    heading.className = 'track-heading';

    const title = document.createElement('strong');
    title.className = 'track-title';
    title.textContent = `${index + 1}. ${track.title || 'Unknown track'}`;
    title.title = track.title || 'Unknown track';
    heading.append(title);

    if (track.duration) {
      const duration = document.createElement('span');
      duration.className = 'track-duration';
      duration.textContent = track.duration;
      heading.append(duration);
    }

    const meta = document.createElement('span');
    meta.className = 'track-meta';
    meta.textContent = [track.artists, track.album].filter(Boolean).join(' · ');
    meta.title = meta.textContent;

    copy.append(heading, meta);

    const link = document.createElement('a');
    link.href = track.url || `https://music.youtube.com/watch?v=${encodeURIComponent(track.video_id || '')}`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Play';

    item.append(artwork, copy, link);
    return item;
  }

  let data = null;
  try {
    data = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
  } catch {
    data = null;
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
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  });
  titleInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      titleInput.blur();
    }
  });

  const totalSeconds = data.tracks.reduce(
    (total, track) => total + durationToSeconds(track.duration),
    0,
  );
  const durationText = formatPlaylistDuration(totalSeconds);
  const trackLabel = `${data.tracks.length} ${data.tracks.length === 1 ? 'track' : 'tracks'}`;
  $('playlist-summary').textContent = durationText ? `${trackLabel} · ${durationText}` : trackLabel;
  $('playlist-description').textContent = data.description || data.prompt || '';
  $('track-list').replaceChildren(...data.tracks.map(renderTrack));
})();
