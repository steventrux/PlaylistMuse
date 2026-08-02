(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;

  function ensurePanel() {
    const existing = $('setup-lastfm-step');
    if (existing) return existing;

    const navigation = $('setup-navigation');
    const form = $('setup-dialog')?.querySelector('form');
    if (!form) return null;

    const panel = document.createElement('section');
    panel.id = 'setup-lastfm-step';
    panel.className = 'settings-block setup-step lastfm-settings-panel hidden';
    panel.innerHTML = `
      <div class="youtube-account-summary">
        <div class="youtube-account-summary-heading">
          <h3>Last.fm recommendations</h3>
          <p id="lastfm-settings-status" class="settings-status">Checking…</p>
        </div>
      </div>

      <div class="youtube-credentials-section">
        <h3>API access</h3>
        <div class="settings-fields">
          <label for="lastfm-api-key">Last.fm API key
            <input id="lastfm-api-key" type="password" autocomplete="off" placeholder="Enter your Last.fm API key">
            <span id="lastfm-api-key-hint" class="field-hint"></span>
          </label>
        </div>

        <p class="field-hint lastfm-settings-help">
          The key enables listening-data recommendations for playlists created from a seed track.
          <a href="https://www.last.fm/api/account/create" target="_blank" rel="noopener noreferrer">Create a Last.fm API account</a>
        </p>

        <div class="settings-actions">
          <button id="save-lastfm" type="button" class="primary">Save Last.fm key</button>
          <button id="disconnect-lastfm" type="button" class="secondary hidden">Remove saved key</button>
        </div>
      </div>
    `;
    if (navigation) form.insertBefore(panel, navigation);
    else form.append(panel);
    return panel;
  }

  function hidePanel() {
    $('setup-lastfm-step')?.classList.add('hidden');
  }

  function setStatus(text, error = false) {
    const status = $('lastfm-settings-status');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('error', error);
  }

  function openSettings() {
    const dialog = $('setup-dialog');
    const lastFmPanel = ensurePanel();
    if (!dialog || !lastFmPanel) return false;

    $('ai-open-settings')?.click();
    $('setup-eyebrow').textContent = 'Configuration';
    $('setup-title').textContent = 'Last.fm Settings';
    $('setup-intro').classList.add('hidden');
    $('setup-progress').classList.add('hidden');
    $('setup-navigation').classList.add('hidden');
    $('setup-ai-step').classList.add('hidden');
    $('setup-youtube-step').classList.add('hidden');
    lastFmPanel.classList.remove('hidden');
    if (!dialog.open) dialog.showModal();
    window.dispatchEvent(new Event('playlistmuse-lastfm-settings-opened'));
    return true;
  }

  function renderSettings(data) {
    const configured = Boolean(data.configured);
    const source = data.source || '';
    const input = $('lastfm-api-key');
    const hint = $('lastfm-api-key-hint');
    const disconnect = $('disconnect-lastfm');

    if (configured && source === 'environment') {
      setStatus('Configured through the server environment.');
      input.placeholder = 'Environment API key active';
      hint.textContent = 'Saving a key here will use the key stored by PlaylistMuse instead.';
    } else if (configured) {
      setStatus('Configured · Last.fm recommendations are active.');
      input.placeholder = 'API key already saved';
      hint.textContent = 'Enter a new key only when you want to replace the saved one.';
    } else {
      setStatus('Not configured · Last.fm recommendations are disabled.');
      input.placeholder = 'Enter your Last.fm API key';
      hint.textContent = 'The key is stored securely and is never returned to the browser.';
    }

    disconnect.classList.toggle('hidden', source !== 'saved');
    input.value = '';
  }

  async function loadSettings() {
    setStatus('Checking Last.fm configuration…');
    try {
      const data = await readJson(await fetch('/api/lastfm/settings', {cache: 'no-store'}));
      renderSettings(data);
    } catch (error) {
      setStatus(error.message || 'Unable to check Last.fm configuration.', true);
    }
  }

  async function saveSettings() {
    const input = $('lastfm-api-key');
    const button = $('save-lastfm');
    const apiKey = input.value.trim();
    if (!apiKey) {
      setStatus('Enter a Last.fm API key before saving.', true);
      input.focus();
      return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Saving…';
    setStatus('Saving Last.fm configuration…');

    try {
      const data = await readJson(await fetch('/api/lastfm/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({api_key: apiKey}),
      }), {flattenValidationErrors: true});
      renderSettings(data);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      setStatus(error.message || 'The Last.fm API key could not be saved.', true);
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }

  async function disconnect() {
    const button = $('disconnect-lastfm');
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Removing…';
    setStatus('Removing the saved Last.fm key…');

    try {
      const data = await readJson(await fetch('/api/lastfm/settings', {
        method: 'DELETE',
      }));
      renderSettings(data);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      setStatus(error.message || 'The saved Last.fm key could not be removed.', true);
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }

  const panel = ensurePanel();
  panel?.querySelector('#save-lastfm')?.addEventListener('click', () => void saveSettings());
  panel?.querySelector('#disconnect-lastfm')?.addEventListener('click', () => void disconnect());
  panel?.querySelector('#lastfm-api-key')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void saveSettings();
    }
  });
  window.PlaylistMuseOpenLastFmSettings = openSettings;
  window.addEventListener('playlistmuse-lastfm-settings-opened', () => void loadSettings());
  window.addEventListener('playlistmuse-ai-settings-opened', hidePanel);
  window.addEventListener('playlistmuse-youtube-settings-opened', hidePanel);
})();
