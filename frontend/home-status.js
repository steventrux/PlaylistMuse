(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function setIndicator(element, connected, title) {
    element.classList.remove('pending', 'on', 'off', 'error');
    element.classList.add(connected ? 'on' : 'off');
    element.title = title;
    element.setAttribute('aria-label', title);
  }

  function setPending(element, title) {
    element.classList.remove('on', 'off', 'error');
    element.classList.add('pending');
    element.title = title;
    element.setAttribute('aria-label', title);
  }

  function setError(element, title) {
    element.classList.remove('pending', 'on', 'off');
    element.classList.add('error');
    element.title = title;
    element.setAttribute('aria-label', title);
  }

  async function refreshStatus() {
    const aiIndicator = $('home-ai-status');
    const ytIndicator = $('home-yt-status');

    aiIndicator.textContent = 'AI';
    ytIndicator.textContent = 'YT';
    setPending(aiIndicator, 'Checking AI provider configuration');
    setPending(ytIndicator, 'Checking YouTube Music account connection');

    try {
      const response = await fetch('/api/settings');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const settings = await response.json();
      setIndicator(
        aiIndicator,
        Boolean(settings.configured),
        settings.configured
          ? `AI connected · ${settings.model}`
          : 'AI not connected · configure a provider in Settings',
      );
    } catch {
      setError(aiIndicator, 'Unable to check AI configuration');
    }

    try {
      const response = await fetch('/api/youtube/status');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();
      const connected = Boolean(status.account_connected);

      setIndicator(
        ytIndicator,
        connected,
        connected
          ? 'YouTube Music account connected'
          : 'YouTube Music account not connected',
      );

      $('account-status').textContent = connected
        ? 'Connected with Google'
        : (status.catalog_available
          ? 'Google account not connected · public catalogue available'
          : 'Google account not connected');
    } catch {
      setError(ytIndicator, 'Unable to check YouTube Music connection');
      $('account-status').textContent = 'Unable to check YouTube Music.';
    }
  }

  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  window.addEventListener('playlistmuse-settings-opened', refreshStatus);
  refreshStatus();
})();
