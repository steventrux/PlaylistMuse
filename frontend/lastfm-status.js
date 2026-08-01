(() => {
  'use strict';

  const SETTINGS_REQUEST_KEY = 'playlistmuse-open-settings';
  const INDICATOR_STATES = ['pending', 'on', 'off', 'error'];
  const lastFmIcon = `
    <svg class="lastfm-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path d="M6.2 19.2c1.4 3.7 3.6 5.8 7.1 5.8 2.1 0 3.7-.7 5-2.1l-2.4-2.2c-.8.8-1.5 1.1-2.5 1.1-1.8 0-2.9-1.2-3.8-3.7l-1.3-3.6c-.8-2.4-2-3.4-3.8-3.4-.5 0-1 .1-1.5.3v-3c.6-.2 1.3-.3 2-.3 3.2 0 5.2 1.8 6.5 5.5l1.3 3.6c.7 2 1.5 2.7 2.8 2.7.9 0 1.7-.4 2.4-1.1l2.3 2.2c-1.3 1.4-2.9 2.1-4.9 2.1-3 0-4.8-1.6-6-5.1l-1.2-3.5c-.6-1.8-1.4-2.5-2.5-2.5-.9 0-1.6.5-2.1 1.2l2.6 6Z" />
      <path d="M20.7 10.2c1.1-1.4 2.5-2.1 4.3-2.1 1.5 0 2.8.5 4 1.4l-1.6 2.7c-.8-.6-1.5-.9-2.3-.9-.9 0-1.6.4-2.1 1.1l-2.3-2.2Z" />
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
