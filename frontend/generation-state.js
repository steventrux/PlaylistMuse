(() => {
  'use strict';

  const PROMPT_MAX_LENGTH = 1950;
  const DEFAULT_TRACK_COUNT = 25;
  const MIN_TRACK_COUNT = 5;
  const MAX_TRACK_COUNT = 100;

  function normalizePrompt(value) {
    return String(value ?? '')
      .trim()
      .replace(/\s+/g, ' ')
      .slice(0, PROMPT_MAX_LENGTH);
  }

  function clampTrackCount(value) {
    const count = Number(value) || DEFAULT_TRACK_COUNT;
    return Math.max(MIN_TRACK_COUNT, Math.min(MAX_TRACK_COUNT, count));
  }

  function isGenerationReady(mode, prompt, selectedSeed) {
    return mode === 'prompt'
      ? Boolean(normalizePrompt(prompt))
      : Boolean(selectedSeed);
  }

  function isSeedSearchEnabled(query, searching = false) {
    return !searching && Boolean(String(query ?? '').trim());
  }

  const api = Object.freeze({
    normalizePrompt,
    clampTrackCount,
    isGenerationReady,
    isSeedSearchEnabled,
  });

  if (typeof window !== 'undefined') {
    window.PlaylistMuseGenerationState = api;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
