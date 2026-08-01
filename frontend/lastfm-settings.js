(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;

  function setStatus(text, error = false) {
    const status = $('lastfm-settings-status');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('error', error);
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

  $('save-lastfm')?.addEventListener('click', () => void saveSettings());
  $('disconnect-lastfm')?.addEventListener('click', () => void disconnect());
  $('lastfm-api-key')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void saveSettings();
    }
  });
  window.addEventListener('playlistmuse-lastfm-settings-opened', () => void loadSettings());
})();
