(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const INDICATOR_STATES = ['pending', 'on', 'off', 'error'];

  function setIndicatorState(element, state, title) {
    element.classList.remove(...INDICATOR_STATES);
    element.classList.add(state);
    element.title = title;
    element.setAttribute('aria-label', title);
  }

  function setGenerationAvailability(state) {
    const button = $('generate');
    const warning = $('ai-generation-warning');
    const warningTitle = $('ai-generation-warning-title');
    const warningText = $('ai-generation-warning-text');
    const configured = state === 'configured';

    button.disabled = !configured;
    button.setAttribute('aria-disabled', String(!configured));
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
      const connected = Boolean(settings.configured);
      setIndicatorState(
        indicator,
        connected ? 'on' : 'off',
        connected
          ? `AI connected · ${settings.model}`
          : 'AI not connected · configure a provider in Settings',
      );
      setGenerationAvailability(connected ? 'configured' : 'unconfigured');
    } catch {
      setIndicatorState(indicator, 'error', 'Unable to check AI configuration');
      setGenerationAvailability('error');
    }
  }

  async function refreshYouTubeStatus(indicator) {
    try {
      const response = await fetch('/api/youtube/status');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();
      const connected = Boolean(status.account_connected);
      const connectedLabel = status.account_name
        ? `YouTube Music connected · ${status.account_name}`
        : 'YouTube Music account connected';

      setIndicatorState(
        indicator,
        connected ? 'on' : 'off',
        connected ? connectedLabel : 'YouTube Music account not connected',
      );
    } catch {
      setIndicatorState(indicator, 'error', 'Unable to check YouTube Music connection');
    }
  }

  async function refreshStatus() {
    const aiIndicator = $('home-ai-status');
    const ytIndicator = $('home-yt-status');

    aiIndicator.textContent = 'AI';
    ytIndicator.textContent = 'YT';
    setIndicatorState(aiIndicator, 'pending', 'Checking AI provider configuration');
    setIndicatorState(ytIndicator, 'pending', 'Checking YouTube Music account connection');
    setGenerationAvailability('pending');

    await Promise.all([
      refreshAiStatus(aiIndicator),
      refreshYouTubeStatus(ytIndicator),
    ]);
  }

  $('ai-open-settings').addEventListener('click', () => $('settings-btn').click());
  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  window.addEventListener('playlistmuse-settings-opened', refreshStatus);
  void refreshStatus();
})();
