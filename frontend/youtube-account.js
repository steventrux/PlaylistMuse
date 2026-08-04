(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const state = {
    pollTimer: null,
    pollInterval: 5000,
    popup: null,
  };

  function stopPolling() {
    if (state.pollTimer) window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  function setAccountStatus(text, kind = '') {
    const element = $('account-status');
    const displayText = {
      Connected: 'YouTube Music account connected.',
      'Not connected': 'YouTube Music account not connected.',
      'OAuth setup required': 'YouTube Music OAuth setup required.',
    }[text] || text;

    element.textContent = displayText;
    element.classList.toggle('ok', kind === 'ok');
    element.classList.toggle('error', kind === 'error');
  }

  function renderProfile(status) {
    const profile = $('youtube-account-profile');
    const photo = $('youtube-account-photo');
    const name = $('youtube-account-name');
    const handle = $('youtube-account-handle');
    const connected = Boolean(status.account_connected);
    const photoUrl = String(status.account_photo_url || '').trim();
    const accountName = String(status.account_name || '').trim();
    const accountHandle = String(status.channel_handle || '').trim();
    const hasAccountDetails = Boolean(accountName || accountHandle);

    // Previous placeholders are intentionally not rendered as account details:
    // status.account_name || 'Connected YouTube Music account'
    // status.channel_handle || 'Google account details unavailable'
    profile.classList.toggle('hidden', !connected || !hasAccountDetails);

    if (!connected || !hasAccountDetails) {
      photo.removeAttribute('src');
      photo.classList.add('hidden');
      profile.classList.remove('no-photo');
      name.textContent = '';
      name.removeAttribute('title');
      handle.textContent = '';
      handle.removeAttribute('title');
      handle.classList.add('hidden');
      return;
    }

    photo.src = photoUrl;
    photo.classList.toggle('hidden', !photoUrl);
    profile.classList.toggle('no-photo', !photoUrl);

    const displayedName = accountName || accountHandle;
    const displayedHandle = accountName ? accountHandle : '';

    name.textContent = displayedName;
    name.title = displayedName;
    handle.textContent = displayedHandle;
    handle.title = displayedHandle;
    handle.classList.toggle('hidden', !displayedHandle);
  }

  function renderStatus(status) {
    const connected = Boolean(status.account_connected);
    const credentialsConfigured = Boolean(status.credentials_configured);
    const connect = $('connect');
    const disconnect = $('disconnect');

    renderProfile(status);
    connect.disabled = !credentialsConfigured || connected;
    disconnect.disabled = !connected;
    connect.classList.toggle('hidden', connected);
    disconnect.classList.toggle('hidden', !connected);

    if (connected) {
      setAccountStatus('Connected', 'ok');
    } else if (!credentialsConfigured) {
      setAccountStatus('OAuth setup required');
    } else {
      setAccountStatus('Not connected');
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
      ? 'OAuth client configured.'
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
    setAccountStatus('Saving OAuth settings…');

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
      $('youtube-credentials-hint').textContent = 'OAuth client configured.';
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
    setAccountStatus('Authorization required');
  }

  function schedulePoll(intervalSeconds) {
    stopPolling();
    const seconds = Math.max(5, Number(intervalSeconds) || 5);
    state.pollInterval = seconds * 1000;
    state.pollTimer = window.setTimeout(pollAuthorization, state.pollInterval);
  }

  function allowConnectionRetry() {
    const connect = $('connect');
    connect.disabled = false;
    connect.textContent = 'Connect account';
  }

  async function pollAuthorization() {
    try {
      const result = await readJson(await fetch('/api/youtube/connect/poll', {
        method: 'POST',
      }));

      if (result.status === 'pending') {
        setAccountStatus('Waiting for authorization…');
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

      allowConnectionRetry();
      setAccountStatus(result.message || 'Google authorization was not completed.', 'error');
    } catch (error) {
      stopPolling();
      allowConnectionRetry();
      setAccountStatus(error.message || String(error), 'error');
    }
  }

  async function connectAccount() {
    const button = $('connect');
    button.disabled = true;
    button.textContent = 'Starting…';
    setAccountStatus('Starting connection…');

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

  const saveButton = $('save-youtube');
  saveButton.classList.remove('secondary');
  saveButton.classList.add('primary');

  saveButton.addEventListener('click', saveSettings);
  $('connect').addEventListener('click', connectAccount);
  $('disconnect').addEventListener('click', disconnectAccount);
  $('youtube-authorization-link').addEventListener('click', () => {
    setAccountStatus('Waiting for authorization…');
  });

  window.addEventListener('playlistmuse-youtube-settings-opened', refresh);
  window.addEventListener('beforeunload', stopPolling);
  refresh();
})();
