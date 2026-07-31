(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const INDICATOR_STATES = ['pending', 'on', 'off', 'error'];
  const SETTINGS_REQUEST_KEY = 'playlistmuse-open-settings';

  function ensureStatusStyles() {
    if (document.querySelector('link[href^="/static/layout.css"]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/layout.css?v=4';
    document.head.append(link);
  }

  function createHeaderStatus() {
    ensureStatusStyles();

    const existing = document.querySelector('.header-service-status');
    if (existing) return existing;

    const header = document.querySelector('.app-header');
    if (!header) return null;

    const controls = document.createElement('div');
    controls.className = 'header-actions header-service-status';
    controls.setAttribute('aria-label', 'Service configuration status');
    controls.innerHTML = `
      <button
        id="header-ai-status"
        class="header-indicator ai pending"
        type="button"
        data-tooltip="Checking AI provider configuration"
        aria-label="Checking AI provider configuration"
      >
        <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <path class="brain-outline" d="M13.2 6.1a4.2 4.2 0 0 0-7.3 3 4.7 4.7 0 0 0-2.6 7.7 4.4 4.4 0 0 0 3.4 7.1 4.2 4.2 0 0 0 6.5 2.1" />
          <path class="brain-outline" d="M18.8 6.1a4.2 4.2 0 0 1 7.3 3 4.7 4.7 0 0 1 2.6 7.7 4.4 4.4 0 0 1-3.4 7.1 4.2 4.2 0 0 1-6.5 2.1" />
          <path class="brain-outline" d="M13.2 6.1c1.3.7 2 1.9 2 3.5v3.1M18.8 6.1c-1.3.7-2 1.9-2 3.5v3.1M9.1 11.1c1.7.2 2.8 1.1 3.2 2.7M22.9 11.1c-1.7.2-2.8 1.1-3.2 2.7M8 20.7c1.9-.5 3.4 0 4.5 1.5M24 20.7c-1.9-.5-3.4 0-4.5 1.5" />
          <path class="brain-bolt" d="m17.2 10-5 7.8h4.1l-1.4 5.4 5.1-7.7h-4.2l1.4-5.5Z" />
        </svg>
      </button>
      <button
        id="header-youtube-status"
        class="header-indicator youtube pending"
        type="button"
        data-tooltip="Checking YouTube Music configuration"
        aria-label="Checking YouTube Music configuration"
      >
        <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <rect class="youtube-body" x="3.5" y="8" width="25" height="16" rx="5.5" />
          <path class="youtube-play" d="m13.4 12.4 7.2 3.6-7.2 3.6v-7.2Z" />
        </svg>
      </button>
    `;
    header.append(controls);
    return controls;
  }

  function setIndicatorState(element, state, tooltip) {
    if (!element) return;
    element.classList.remove(...INDICATOR_STATES);
    element.classList.add(state);
    element.dataset.tooltip = tooltip;
    element.title = tooltip;
    element.setAttribute('aria-label', tooltip);
  }

  function setGenerationAvailability(state) {
    const button = $('generate');
    const warning = $('ai-generation-warning');
    if (!button || !warning) return;

    const warningTitle = $('ai-generation-warning-title');
    const warningText = $('ai-generation-warning-text');
    const configured = state === 'configured';

    button.disabled = !configured;
    button.setAttribute('aria-disabled', String(!configured));
    button.classList.toggle('hidden', !configured);
    warning.classList.toggle('hidden', configured || state === 'pending');

    if (state === 'unconfigured') {
      warningTitle.textContent = 'AI provider not configured';
      warningText.textContent = 'Configure an AI provider before generating a playlist.';
    } else if (state === 'error') {
      warningTitle.textContent = 'AI configuration could not be verified';
      warningText.textContent = 'Open AI Settings and check the provider configuration before generating.';
    }
  }

  async function refreshAiStatus(indicator) {
    try {
      const response = await fetch('/api/settings');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const settings = await response.json();
      const configured = Boolean(settings.configured);
      setIndicatorState(
        indicator,
        configured ? 'on' : 'off',
        configured
          ? `AI configured · ${settings.model}`
          : 'AI not configured · click to open AI Settings',
      );
      setGenerationAvailability(configured ? 'configured' : 'unconfigured');
    } catch {
      setIndicatorState(indicator, 'error', 'Unable to check AI configuration · click to open AI Settings');
      setGenerationAvailability('error');
    }
  }

  async function refreshYouTubeStatus(indicator) {
    try {
      const response = await fetch('/api/youtube/status');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();
      const connected = Boolean(status.account_connected);
      let tooltip;

      if (connected) {
        tooltip = status.account_name
          ? `YouTube Music configured · ${status.account_name}`
          : 'YouTube Music configured and connected';
      } else if (status.credentials_configured) {
        tooltip = 'YouTube Music credentials saved · click to connect the account';
      } else {
        tooltip = 'YouTube Music not configured · click to open YouTube Settings';
      }

      setIndicatorState(indicator, connected ? 'on' : 'off', tooltip);
    } catch {
      setIndicatorState(
        indicator,
        'error',
        'Unable to check YouTube Music configuration · click to open YouTube Settings',
      );
    }
  }

  function openSettings(section) {
    const homeAiSettings = $('ai-open-settings');
    if (homeAiSettings) {
      homeAiSettings.click();
      if (section === 'youtube') {
        setTimeout(() => $('setup-next')?.click(), 0);
      }
      return;
    }

    if (section === 'youtube' && $('youtube-open-settings')) {
      $('youtube-open-settings').click();
      return;
    }

    sessionStorage.setItem(SETTINGS_REQUEST_KEY, section);
    window.location.assign('/');
  }

  function bindIndicatorActions() {
    $('header-ai-status')?.addEventListener('click', () => openSettings('ai'));
    $('header-youtube-status')?.addEventListener('click', () => openSettings('youtube'));
  }

  function restoreRequestedSettings() {
    const requested = sessionStorage.getItem(SETTINGS_REQUEST_KEY);
    if (!['ai', 'youtube'].includes(requested)) return;
    sessionStorage.removeItem(SETTINGS_REQUEST_KEY);
    setTimeout(() => openSettings(requested), 0);
  }

  async function refreshStatus() {
    createHeaderStatus();
    const aiIndicator = $('header-ai-status');
    const youtubeIndicator = $('header-youtube-status');

    setIndicatorState(aiIndicator, 'pending', 'Checking AI provider configuration');
    setIndicatorState(youtubeIndicator, 'pending', 'Checking YouTube Music configuration');
    setGenerationAvailability('pending');

    await Promise.all([
      refreshAiStatus(aiIndicator),
      refreshYouTubeStatus(youtubeIndicator),
    ]);
  }

  createHeaderStatus();
  bindIndicatorActions();
  restoreRequestedSettings();
  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  void refreshStatus();
})();
