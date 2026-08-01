(() => {
  'use strict';

  if (document.getElementById('ai-settings-dialog')) return;

  const dialog = document.createElement('dialog');
  dialog.id = 'ai-settings-dialog';
  dialog.innerHTML = `
    <form method="dialog" class="dialog-card settings-dialog-card" novalidate>
      <div class="dialog-head">
        <h2>AI Settings</h2>
        <button id="close-ai-settings" type="button" class="icon" aria-label="Close">×</button>
      </div>

      <section class="settings-block">
        <div class="ai-active-summary">
          <p id="ai-active-status" class="settings-status ai-active-status">
            Checking active AI provider…
          </p>
        </div>

        <div class="ai-provider-selection">
          <div class="ai-provider-selection-heading">
            <h3>Choose or configure a provider</h3>
            <p class="ai-provider-legend" aria-label="Provider status symbols">
              <span><strong>✓</strong> In use</span>
              <span><strong>●</strong> Configured</span>
            </p>
          </div>

          <p id="ai-status" class="settings-status">Checking selected provider…</p>

          <div class="settings-fields">
            <label for="ai-provider">Provider
              <select id="ai-provider">
                <option value="gemini">Google Gemini</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="openrouter_auto">OpenRouter Auto</option>
                <option value="openrouter_free">OpenRouter Free</option>
                <option value="ollama">Ollama</option>
                <option value="custom">OpenAI-compatible endpoint</option>
              </select>
            </label>

            <p id="provider-help" class="field-hint provider-help">
              <a id="provider-help-link" href="#" target="_blank" rel="noopener noreferrer"></a>
            </p>

            <label id="api-key-field" for="ai-key">API key
              <input id="ai-key" type="password" autocomplete="off" placeholder="Enter the provider API key">
              <span id="api-key-hint" class="field-hint"></span>
            </label>

            <label id="base-url-field" class="hidden" for="ai-base-url">Server URL
              <input id="ai-base-url" type="url" placeholder="http://host:11434 or https://example.com/v1">
            </label>

            <label for="ai-model">Primary model
              <input id="ai-model" placeholder="Primary model identifier">
            </label>

            <div id="fallback-row" class="fallback-row" aria-label="Fallback models">
              <span class="field-hint fallback-label">Fallbacks</span>
              <input id="ai-fallback-1" placeholder="Fallback 1" aria-label="Fallback model 1">
              <span class="fallback-arrow">→</span>
              <input id="ai-fallback-2" placeholder="Fallback 2" aria-label="Fallback model 2">
            </div>
          </div>

          <div class="settings-actions">
            <button id="save-ai" type="button" class="primary">Save AI settings</button>
          </div>
        </div>
      </section>
    </form>
  `;

  document.body.append(dialog);

  document.getElementById('close-ai-settings').addEventListener('click', () => {
    dialog.close();
  });

  document.addEventListener('click', (event) => {
    const indicator = event.target.closest?.('#header-ai-status');
    if (!indicator) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    if (!dialog.open) dialog.showModal();
    window.dispatchEvent(new Event('playlistmuse-ai-settings-opened'));
  }, true);
})();
