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
      <div class="settings-summary">
        <div class="settings-summary-heading">
          <h3>Last.fm recommendations</h3>
          <p id="lastfm-settings-status" class="settings-status settings-state">Checking…</p>
        </div>
      </div>

      <div class="settings-section">
        <h3>API access</h3>
        <div class="settings-fields">
          <label for="lastfm-api-key">Last.fm API key
            <input id="lastfm-api-key" type="password" autocomplete="off" placeholder="Enter your Last.fm API key">
            <span id="lastfm-api-key-hint" class="field-hint"></span>
          </label>
        </div>

        <p class="field-hint settings-help lastfm-settings-help">
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

  function setStatus(text, state = '') {
    const status = $('lastfm-settings-status');
    if (!status) return;

    const displayText = {
      Configured: 'Last.fm API connected.',
      'Server managed': 'Last.fm API connected · server managed.',
      'Not configured': 'Last.fm API not connected.',
    }[text] || text;

    status.textContent = displayText;
    status.classList.toggle('ok', state === 'ok');
    status.classList.toggle('error', state === 'error');
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
      setStatus('Server managed', 'ok');
      input.placeholder = 'Environment API key active';
      hint.textContent = 'A server environment key is active. Saving a key here will use the key stored by PlaylistMuse instead.';
    } else if (configured) {
      setStatus('Configured', 'ok');
      input.placeholder = 'API key already saved';
      hint.textContent = 'Last.fm recommendations are active. Enter a new key only when you want to replace the saved one.';
    } else {
      setStatus('Not configured');
      input.placeholder = 'Enter your Last.fm API key';
      hint.textContent = 'The key is stored securely and is never returned to the browser.';
    }

    disconnect.classList.toggle('hidden', source !== 'saved');
    input.value = '';
  }

  async function loadSettings() {
    setStatus('Checking…');
    try {
      const data = await readJson(await fetch('/api/lastfm/settings', {cache: 'no-store'}));
      renderSettings(data);
    } catch (error) {
      setStatus(error.message || 'Unable to check Last.fm configuration.', 'error');
    }
  }

  async function saveSettings() {
    const input = $('lastfm-api-key');
    const button = $('save-lastfm');
    const apiKey = input.value.trim();
    if (!apiKey) {
      setStatus('API key required', 'error');
      input.focus();
      return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Saving…';
    setStatus('Saving…');

    try {
      const data = await readJson(await fetch('/api/lastfm/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({api_key: apiKey}),
      }), {flattenValidationErrors: true});
      renderSettings(data);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      setStatus(error.message || 'The Last.fm API key could not be saved.', 'error');
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
    setStatus('Removing…');

    try {
      const data = await readJson(await fetch('/api/lastfm/settings', {
        method: 'DELETE',
      }));
      renderSettings(data);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      setStatus(error.message || 'The saved Last.fm key could not be removed.', 'error');
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
