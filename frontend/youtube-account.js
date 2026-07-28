(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = {
    pollTimer: null,
    pollInterval: 5000,
    popup: null,
  };

  async function readJson(response) {
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(text || `HTTP ${response.status}`);
    }
    if (!response.ok) {
      const detail = payload.detail ?? payload.error ?? payload.message;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || payload));
    }
    return payload;
  }

  function stopPolling() {
    if (state.pollTimer) window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  function setAccountStatus(text, kind = '') {
    const element = $('account-status');
    element.textContent = text;
    element.classList.toggle('ok', kind === 'ok');
    element.classList.toggle('error', kind === 'error');
  }

  function renderProfile(status) {
    const profile = $('youtube-account-profile');
    const connected = Boolean(status.account_connected);
    profile.classList.toggle('hidden', !connected);
    if (!connected) return;

    const photo = $('youtube-account-photo');
    const photoUrl = status.account_photo_url || '';
    photo.src = photoUrl;
    photo.classList.toggle('hidden', !photoUrl);
    $('youtube-account-name').textContent = status.account_name || 'Connected account';
    $('youtube-account-handle').textContent = status.channel_handle || 'YouTube Music';
  }

  function renderStatus(status) {
    const connected = Boolean(status.account_connected);
    const credentialsConfigured = Boolean(status.credentials_configured);

    renderProfile(status);
    $('connect').disabled = !credentialsConfigured || connected;
    $('disconnect').disabled = !connected;

    if (connected) {
      setAccountStatus(status.message || 'YouTube Music account connected.', 'ok');
    } else if (!credentialsConfigured) {
      setAccountStatus('Save a Google OAuth client before connecting an account.');
    } else {
      setAccountStatus(status.message || 'Google OAuth client configured · account not connected.');
    }
  }

  async function loadSettings() {
    const settings = await readJson(await fetch('/api/youtube/settings'));
    $('youtube-client-id').value = settings.client_id || '';
    $('youtube-client-secret').value = '';
    $('youtube-client-secret').placeholder = settings.client_secret_set
      ? 'Saved — leave blank to keep it'
      : 'Google OAuth client secret';
    $('youtube-credentials-hint').textContent = settings.configured
      ? 'OAuth client saved. You can connect your YouTube Music account.'
      : 'Create an OAuth client of type “TVs and Limited Input devices”.';
    return settings;
  }

  async function loadStatus() {
    const status = await readJson(await fetch('/api/youtube/status'));
    renderStatus(status);
    return status;
  }

  async function refresh() {
    try {
      await Promise.all([loadSettings(), loadStatus()]);
    } catch (error) {
      setAccountStatus(error.message || String(error), 'error');
    }
  }

  async function saveSettings() {
    const button = $('save-youtube');
    const clientId = $('youtube-client-id').value.trim();
    const clientSecret = $('youtube-client-secret').value.trim();

    button.disabled = true;
    button.textContent = 'Saving…';
    setAccountStatus('Saving Google OAuth credentials…');

    try {
      const settings = await readJson(await fetch('/api/youtube/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({client_id: clientId, client_secret: clientSecret}),
      }));
      $('youtube-client-secret').value = '';
      $('youtube-client-secret').placeholder = settings.client_secret_set
        ? 'Saved — leave blank to keep it'
        : 'Google OAuth client secret';
      $('youtube-credentials-hint').textContent = 'OAuth client saved.';
      await loadStatus();
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      setAccountStatus(error.message || String(error), 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Save Google credentials';
    }
  }

  function showAuthorization(flow) {
    $('youtube-user-code').textContent = flow.user_code || '';
    const link = $('youtube-authorization-link');
    link.href = flow.verification_url_complete || flow.verification_url || '#';
    $('youtube-device-flow').classList.remove('hidden');
    setAccountStatus('Complete the Google authorization in the opened page.');
  }

  function schedulePoll(intervalSeconds) {
    stopPolling();
    const seconds = Math.max(5, Number(intervalSeconds) || 5);
    state.pollInterval = seconds * 1000;
    state.pollTimer = window.setTimeout(pollAuthorization, state.pollInterval);
  }

  async function pollAuthorization() {
    try {
      const result = await readJson(await fetch('/api/youtube/connect/poll', {
        method: 'POST',
      }));

      if (result.status === 'pending') {
        setAccountStatus(result.message || 'Waiting for Google authorization…');
        schedulePoll(result.interval);
        return;
      }

      stopPolling();
      if (result.status === 'connected') {
        $('youtube-device-flow').classList.add('hidden');
        renderStatus({
          ...result,
          credentials_configured: true,
          account_connected: true,
        });
        window.dispatchEvent(new Event('playlistmuse-status-changed'));
        return;
      }

      setAccountStatus(result.message || 'Google authorization was not completed.', 'error');
    } catch (error) {
      stopPolling();
      setAccountStatus(error.message || String(error), 'error');
    }
  }

  async function connectAccount() {
    const button = $('connect');
    button.disabled = true;
    button.textContent = 'Starting…';
    setAccountStatus('Requesting a Google authorization code…');

    try {
      state.popup = window.open('about:blank', 'playlistmuse-google-oauth');
      if (state.popup) {
        state.popup.document.title = 'PlaylistMuse · Google authorization';
        state.popup.document.body.textContent = 'Preparing Google authorization…';
      }

      const flow = await readJson(await fetch('/api/youtube/connect/start', {
        method: 'POST',
      }));
      showAuthorization(flow);

      const authorizationUrl = flow.verification_url_complete || flow.verification_url;
      if (state.popup && authorizationUrl) {
        state.popup.location.assign(authorizationUrl);
      }
      schedulePoll(flow.interval);
    } catch (error) {
      if (state.popup && !state.popup.closed) state.popup.close();
      setAccountStatus(error.message || String(error), 'error');
      button.disabled = false;
    } finally {
      button.textContent = 'Connect account';
    }
  }

  async function disconnectAccount() {
    if (!window.confirm('Disconnect the YouTube Music account from PlaylistMuse?')) return;

    const button = $('disconnect');
    button.disabled = true;
    button.textContent = 'Disconnecting…';
    stopPolling();

    try {
      const result = await readJson(await fetch('/api/youtube/connection', {
        method: 'DELETE',
      }));
      $('youtube-device-flow').classList.add('hidden');
      renderStatus({
        ...result,
        credentials_configured: true,
        account_connected: false,
      });
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      setAccountStatus(error.message || String(error), 'error');
    } finally {
      button.textContent = 'Disconnect';
      await loadStatus().catch(() => {});
    }
  }

  $('save-youtube').addEventListener('click', saveSettings);
  $('connect').addEventListener('click', connectAccount);
  $('disconnect').addEventListener('click', disconnectAccount);
  $('youtube-authorization-link').addEventListener('click', () => {
    setAccountStatus('Waiting for Google authorization…');
  });

  window.addEventListener('playlistmuse-settings-opened', refresh);
  window.addEventListener('beforeunload', stopPolling);
  refresh();
})();
