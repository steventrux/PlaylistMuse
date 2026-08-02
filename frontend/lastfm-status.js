(() => {
  'use strict';

  const SETTINGS_REQUEST_KEY = 'playlistmuse-open-settings';
  const INDICATOR_STATES = ['pending', 'on', 'off', 'error'];
  const lastFmIcon = `
    <svg class="lastfm-mark" viewBox="0 0 512 512" aria-hidden="true" focusable="false">
      <path d="M225.8 367.1l-18.8-51s-30.5 34-76.2 34c-40.5 0-69.2-35.2-69.2-91.5 0-72.1 36.4-97.9 72.1-97.9 66.5 0 74.8 53.3 100.9 134.9 18.8 56.9 54 102.6 155.4 102.6 72.7 0 122-22.3 122-80.9 0-72.9-62.7-80.6-115-92.1-25.8-5.9-33.4-16.4-33.4-34 0-19.9 15.8-31.7 41.6-31.7 28.2 0 43.4 10.6 45.7 35.8l58.6-7c-4.7-52.8-41.1-74.5-100.9-74.5-52.8 0-104.4 19.9-104.4 83.9 0 39.9 19.4 65.1 68 76.8 44.9 10.6 79.8 13.8 79.8 45.7 0 21.7-21.1 30.5-61 30.5-59.2 0-83.9-31.1-97.9-73.9-32-96.8-43.6-163-161.3-163C45.7 113.8 0 168.3 0 261c0 89.1 45.7 137.2 127.9 137.2 66.2 0 97.9-31.1 97.9-31.1z" />
    </svg>
  `;

  function setState(element, state, tooltip) {
    element.classList.remove(...INDICATOR_STATES);
    element.classList.add(state);
    element.dataset.tooltip = tooltip;
    element.title = tooltip;
    element.setAttribute('aria-label', tooltip);
  }

  function createIndicator() {
    const existing = document.getElementById('header-lastfm-status');
    if (existing) return existing;

    const controls = document.querySelector('.header-service-status');
    if (!controls) return null;

    const button = document.createElement('button');
    button.id = 'header-lastfm-status';
    button.className = 'header-indicator lastfm pending';
    button.type = 'button';
    button.innerHTML = lastFmIcon;
    setState(button, 'pending', 'Checking Last.fm configuration');
    button.addEventListener('click', openSettings);
    controls.append(button);
    return button;
  }

  function openSettings() {
    if (typeof window.PlaylistMuseOpenLastFmSettings === 'function') {
      window.PlaylistMuseOpenLastFmSettings();
      return;
    }

    sessionStorage.setItem(SETTINGS_REQUEST_KEY, 'lastfm');
    window.location.assign('/');
  }

  async function refreshStatus() {
    const indicator = createIndicator();
    if (!indicator) return;
    setState(indicator, 'pending', 'Checking Last.fm configuration');

    try {
      const response = await fetch('/api/lastfm/status', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();
      const configured = Boolean(status.configured);
      setState(
        indicator,
        configured ? 'on' : 'off',
        configured
          ? 'Last.fm configured · recommendations active'
          : 'Last.fm not configured · click to add an API key',
      );
    } catch {
      setState(
        indicator,
        'error',
        'Unable to check Last.fm configuration · click to open Last.fm Settings',
      );
    }
  }

  function restoreRequestedSettings() {
    if (sessionStorage.getItem(SETTINGS_REQUEST_KEY) !== 'lastfm') return;
    sessionStorage.removeItem(SETTINGS_REQUEST_KEY);
    setTimeout(openSettings, 0);
  }

  createIndicator();
  restoreRequestedSettings();
  window.addEventListener('playlistmuse-status-changed', () => void refreshStatus());
  void refreshStatus();
})();
