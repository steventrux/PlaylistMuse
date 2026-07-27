(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function renderTrack(track, index) {
    const item = document.createElement('li');
    item.className = 'track';

    const artwork = document.createElement('img');
    artwork.loading = 'lazy';
    artwork.alt = '';
    artwork.src = track.thumbnail_url || '';

    const copy = document.createElement('div');
    copy.className = 'track-copy';
    const title = document.createElement('strong');
    title.textContent = `${index + 1}. ${track.title || 'Unknown track'}`;
    const meta = document.createElement('span');
    meta.textContent = [track.artists, track.album, track.duration].filter(Boolean).join(' · ');
    copy.append(title, meta);

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
    data = JSON.parse(sessionStorage.getItem('playlistmuse-generated-playlist') || 'null');
  } catch {
    data = null;
  }

  if (!data || !Array.isArray(data.tracks)) {
    $('empty-state').classList.remove('hidden');
    $('resolved-count').textContent = '';
    return;
  }

  $('playlist-name').textContent = data.name || 'Generated playlist';
  $('playlist-prompt').textContent = data.prompt || '';
  $('resolved-count').textContent = `${data.resolved_count ?? data.tracks.length}/${data.requested_count ?? data.tracks.length} resolved`;
  $('track-list').replaceChildren(...data.tracks.map(renderTrack));
})();
