(() => {
  'use strict';

  function promptText() {
    const value = document.getElementById('prompt')?.value || '';
    return String(value).trim().replace(/\s+/g, ' ');
  }

  function feedback() {
    let node = document.getElementById('prompt-validation-feedback');
    if (!node) {
      node = document.createElement('div');
      node.id = 'prompt-validation-feedback';
      node.className = 'generation-feedback hidden';
      node.setAttribute('role', 'alert');
      node.setAttribute('aria-live', 'assertive');
      document.getElementById('prompt')?.insertAdjacentElement('afterend', node);
    }
    return node;
  }

  function render(result) {
    const node = feedback();
    const status = String(result?.status || 'valid').toLowerCase();
    if (status === 'valid') {
      node.textContent = '';
      node.className = 'generation-feedback hidden';
      return;
    }
    node.textContent = Array.isArray(result?.reasons)
      ? result.reasons.join(' ')
      : 'The request contains incompatible constraints.';
    node.className = status === 'impossible'
      ? 'generation-feedback generation-feedback-impossible'
      : 'generation-feedback generation-feedback-incomplete';
    node.dataset.feedbackIcon = status === 'impossible' ? '⚠' : '◇';
  }

  async function validate() {
    const response = await fetch('/api/playlists/validate-prompt', {
      method: 'POST',
      cache: 'no-store',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: promptText()}),
    });
    return window.PlaylistMuseCommon.readJson(response, {
      flattenValidationErrors: true,
    });
  }

  window.PlaylistMusePromptValidationGuard = {promptText, render, validate};
  document.getElementById('prompt')?.addEventListener('input', () => render({status: 'valid'}));
})();
