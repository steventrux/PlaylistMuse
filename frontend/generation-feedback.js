(() => {
  'use strict';

  const status = document.getElementById('status');
  if (!status) return;

  const INCOMPLETE_RE = /found only\s+\d+\s+of\s+\d+\s+distinct tracks/i;
  const IMPOSSIBLE_RE = /(?:request|prompt).*(?:impossible|incompatible)|(?:impossibile|incompatibil)/i;

  function feedbackType(text) {
    if (!text) return '';
    if (INCOMPLETE_RE.test(text)) return 'incomplete';
    if (IMPOSSIBLE_RE.test(text)) return 'impossible';
    if (status.classList.contains('error')) return 'error';
    return '';
  }

  function updateFeedback() {
    const text = status.textContent.trim();
    const type = feedbackType(text);
    status.classList.remove(
      'generation-feedback',
      'generation-feedback-incomplete',
      'generation-feedback-impossible',
      'generation-feedback-error',
    );
    status.removeAttribute('data-feedback-icon');

    if (!type) return;
    status.classList.add('generation-feedback', `generation-feedback-${type}`);
    status.dataset.feedbackIcon = type === 'incomplete' ? '◔' : type === 'impossible' ? '⛔' : '!';
  }

  new MutationObserver(updateFeedback).observe(status, {
    characterData: true,
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class'],
  });
  updateFeedback();
})();
