(() => {
  'use strict';

  const HISTORY_KEY = 'playlistmuse-replacement-history';
  const MAX_HISTORY = 200;
  const MAX_EXISTING_TRACKS = 300;
  const originalFetch = window.fetch.bind(window);

  function normalize(value) {
    return String(value || '')
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }

  function trackIdentity(track) {
    const title = normalize(track?.title);
    const artists = normalize(track?.artists);
    if (title && artists) return `track:${artists}::${title}`;

    const videoId = String(track?.video_id || '').trim();
    return videoId ? `video:${videoId}` : '';
  }

  function trackContext(track) {
    return {
      video_id: track?.video_id || null,
      title: track?.title || 'Unknown track',
      artists: track?.artists || 'Unknown artist',
      description: track?.description || '',
      reason: track?.reason || '',
    };
  }

  function readHistory() {
    try {
      const stored = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
      return Array.isArray(stored) ? stored : [];
    } catch {
      return [];
    }
  }

  function writeHistory(history) {
    const uniqueNewestFirst = [];
    const seen = new Set();

    for (const track of [...history].reverse()) {
      const identity = trackIdentity(track);
      if (!identity || seen.has(identity)) continue;
      seen.add(identity);
      uniqueNewestFirst.push(trackContext(track));
    }

    const chronological = uniqueNewestFirst.reverse().slice(-MAX_HISTORY);
    sessionStorage.setItem(HISTORY_KEY, JSON.stringify(chronological));
  }

  function mergeReplacementContext(existingTracks) {
    const merged = [];
    const seen = new Set();

    for (const track of existingTracks || []) {
      const identity = trackIdentity(track);
      if (!identity || seen.has(identity)) continue;
      seen.add(identity);
      merged.push(trackContext(track));
      if (merged.length >= MAX_EXISTING_TRACKS) return merged;
    }

    const recentHistory = readHistory().reverse();
    for (const track of recentHistory) {
      const identity = trackIdentity(track);
      if (!identity || seen.has(identity)) continue;
      seen.add(identity);
      merged.push(trackContext(track));
      if (merged.length >= MAX_EXISTING_TRACKS) break;
    }

    return merged;
  }

  function requestUrl(input) {
    return typeof input === 'string' ? input : String(input?.url || '');
  }

  window.fetch = async (input, init = {}) => {
    const url = requestUrl(input);
    const isReplacement = /\/api\/playlists\/replace-track(?:\?|$)/.test(url);
    const isNewPlaylist = /\/api\/playlists\/generate(?:-from-(?:seed|journey))?(?:\/stream)?(?:\?|$)/.test(url);
    let nextInit = init;
    let replacedTrack = null;

    if (isReplacement && typeof init.body === 'string') {
      try {
        const payload = JSON.parse(init.body);
        replacedTrack = payload.current_track || null;
        payload.existing_tracks = mergeReplacementContext(payload.existing_tracks);
        nextInit = {...init, body: JSON.stringify(payload)};
      } catch {
        // Let the original request handle malformed input normally.
      }
    }

    const response = await originalFetch(input, nextInit);
    if (!response.ok) return response;

    if (isNewPlaylist) {
      sessionStorage.removeItem(HISTORY_KEY);
    } else if (isReplacement && replacedTrack) {
      writeHistory([...readHistory(), replacedTrack]);
    }

    return response;
  };
})();
