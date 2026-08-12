(() => {
  'use strict';

  let approvedClick = false;
  let validating = false;

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
      const prompt = document.getElementById('prompt');
      const shell = prompt?.closest('.prompt-input-shell');
      (shell || prompt)?.insertAdjacentElement('afterend', node);
    }
    return node;
  }

  function render(result) {
    const node = feedback();
    const status = String(result?.status || 'valid').toLowerCase();
    if (status === 'valid') {
      node.textContent = '';
      node.className = 'generation-feedback hidden';
      node.removeAttribute('data-feedback-icon');
      return;
    }

    const reasons = Array.isArray(result?.reasons)
      ? result.reasons.filter(Boolean)
      : [];
    node.textContent = reasons.join(' ') || (
      status === 'impossible'
        ? 'The request contains mutually incompatible constraints.'
        : 'The request may be interpreted in more than one way.'
    );
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

  function filterConflicts() {
    const conflicts = window.PlaylistMusePromptComplexity?.activeFilterConflicts?.();
    return Array.isArray(conflicts) ? conflicts : [];
  }

  async function intercept(event) {
    const button = event.target.closest?.('#generate');
    if (!button) return;
    if (approvedClick) {
      approvedClick = false;
      return;
    }

    const promptMode = document.querySelector('.mode.active')?.dataset.mode === 'prompt';
    if (!promptMode || validating || !promptText()) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const conflicts = filterConflicts();
    if (conflicts.length) {
      render({
        status: 'impossible',
        reasons: conflicts.map((item) => item.message).filter(Boolean),
      });
      return;
    }

    validating = true;
    const submittedPrompt = promptText();

    try {
      const result = await validate();
      if (submittedPrompt !== promptText()) return;
      render(result);
      if (result.status === 'impossible') return;

      approvedClick = true;
      button.click();
    } catch (error) {
      render({
        status: 'impossible',
        reasons: [error.message || String(error)],
      });
    } finally {
      validating = false;
    }
  }

  document.addEventListener('click', intercept, true);
  document.getElementById('prompt')?.addEventListener('input', () => {
    render({status: 'valid'});
  });

  window.PlaylistMusePromptValidationGuard = {filterConflicts, promptText, render, validate};
})();
