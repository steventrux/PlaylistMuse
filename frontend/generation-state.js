(() => {
  'use strict';

  const PROMPT_MAX_LENGTH = 1950;
  const DEFAULT_TRACK_COUNT = 25;
  const MIN_TRACK_COUNT = 5;
  const MAX_TRACK_COUNT = 100;
  const INCOMPLETE_RE = /found only\s+\d+\s+of\s+\d+\s+distinct tracks/i;
  const IMPOSSIBLE_RE = /(?:request|prompt).*(?:impossible|incompatible)|(?:impossibile|incompatibil)/i;

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

  function isGenerationReady(mode, prompt, selectedSeed, journeySelection) {
    if (mode === 'prompt') return Boolean(normalizePrompt(prompt));
    if (mode === 'journey') {
      return Boolean(journeySelection?.start) && Boolean(journeySelection?.end);
    }
    return Boolean(selectedSeed);
  }

  function isSeedSearchEnabled(query, searching = false) {
    return !searching && Boolean(String(query ?? '').trim());
  }

  function feedbackType(text, isError) {
    if (!text) return '';
    if (INCOMPLETE_RE.test(text)) return 'incomplete';
    if (IMPOSSIBLE_RE.test(text)) return 'impossible';
    return isError ? 'error' : '';
  }

  function bindGenerationFeedback(status) {
    if (!status || status.dataset.feedbackBound === 'true') return;
    status.dataset.feedbackBound = 'true';

    const originalParent = status.parentElement;
    const prompt = document.getElementById('prompt');
    const promptShell = prompt?.closest('.prompt-input-shell');
    const promptPanel = document.getElementById('prompt-panel');

    const update = () => {
      const type = feedbackType(
        status.textContent.trim(),
        status.classList.contains('error'),
      );
      status.classList.remove(
        'generation-feedback',
        'generation-feedback-incomplete',
        'generation-feedback-impossible',
        'generation-feedback-error',
      );
      status.removeAttribute('data-feedback-icon');

      const promptVisible = promptPanel && !promptPanel.classList.contains('hidden');
      if (type && prompt && promptVisible) {
        (promptShell || prompt).insertAdjacentElement('afterend', status);
      } else if (originalParent && status.parentElement !== originalParent) {
        originalParent.append(status);
      }

      if (!type) return;
      status.classList.add('generation-feedback', `generation-feedback-${type}`);
      status.dataset.feedbackIcon = type === 'incomplete'
        ? '◔'
        : type === 'impossible' ? '⛔' : '!';
    };

    new MutationObserver(update).observe(status, {
      characterData: true,
      childList: true,
      subtree: true,
    });
    update();
  }

  const api = Object.freeze({
    normalizePrompt,
    clampTrackCount,
    isGenerationReady,
    isSeedSearchEnabled,
    feedbackType,
  });

  if (typeof window !== 'undefined') {
    window.PlaylistMuseGenerationState = api;
    bindGenerationFeedback(document.getElementById('status'));
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
