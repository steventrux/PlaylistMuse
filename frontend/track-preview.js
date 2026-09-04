(function (root, factory) {
  'use strict';

  const api = factory();

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PlaylistMusePreview = api;
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  'use strict';

  const PREVIEW_ENDPOINT = '/api/tracks/preview';

  const lookupCache = new Map();
  let sharedAudio = null;
  let activeUrl = null;
  let activeOnStop = null;

  function readJson(response) {
    if (window.PlaylistMuseCommon && window.PlaylistMuseCommon.readJson) {
      return window.PlaylistMuseCommon.readJson(response);
    }
    return response.json();
  }

  function audioElement() {
    if (!sharedAudio) {
      sharedAudio = new Audio();
      sharedAudio.preload = 'none';
    }
    return sharedAudio;
  }

  function stop() {
    if (sharedAudio) {
      sharedAudio.pause();
      sharedAudio.removeAttribute('src');
    }
    const onStop = activeOnStop;
    activeUrl = null;
    activeOnStop = null;
    if (onStop) onStop();
  }

  async function lookup(track) {
    const cacheKey = track && (track.video_id || `${track.artists || ''}::${track.title || ''}`);
    if (!cacheKey) return null;
    if (lookupCache.has(cacheKey)) return lookupCache.get(cacheKey);

    const title = (track.title || '').trim();
    const artist = (track.artists || '').trim();
    if (!title || !artist) {
      lookupCache.set(cacheKey, null);
      return null;
    }

    const promise = (async () => {
      try {
        const response = await fetch(
          `${PREVIEW_ENDPOINT}?title=${encodeURIComponent(title)}&artist=${encodeURIComponent(artist)}`,
        );
        if (!response.ok) return null;
        const payload = await readJson(response);
        return payload && typeof payload.preview_url === 'string' ? payload.preview_url : null;
      } catch {
        return null;
      }
    })();

    lookupCache.set(cacheKey, promise);
    const resolved = await promise;
    lookupCache.set(cacheKey, resolved);
    return resolved;
  }

  function isActive(url) {
    return Boolean(url) && activeUrl === url;
  }

  function toggle(url, {onStart, onStop} = {}) {
    if (!url) return;

    if (isActive(url)) {
      stop();
      return;
    }

    stop();
    const audio = audioElement();
    audio.src = url;
    activeUrl = url;
    activeOnStop = onStop || null;

    const handleEnded = () => {
      audio.removeEventListener('ended', handleEnded);
      if (activeUrl === url) stop();
    };
    audio.addEventListener('ended', handleEnded);

    audio.play().catch(() => {
      if (activeUrl === url) stop();
    });
    if (onStart) onStart();
  }

  return {lookup, toggle, stop, isActive};
}));
