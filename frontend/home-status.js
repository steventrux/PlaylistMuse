(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function setBadge(element, state, title) {
    element.classList.remove('pending', 'ok', 'warn', 'error');
    element.classList.add(state);
    element.title = title;
  }

  async function refreshStatus() {
    setBadge($('home-ai-status'), 'pending', 'Checking AI provider configuration');
    setBadge($('home-yt-status'), 'pending', 'Checking YouTube Music catalogue');

    try {
      const settings = await fetch('/api/settings').then((response) => response.json());
      setBadge(
        $('home-ai-status'),
        settings.configured ? 'ok' : 'warn',
        settings.configured ? `AI configured: ${settings.model}` : 'AI provider configuration required',
      );
    } catch {
      setBadge($('home-ai-status'), 'error', 'Unable to check AI configuration');
    }

    try {
      const status = await fetch('/api/youtube/status').then((response) => response.json());
      setBadge(
        $('home-yt-status'),
        status.catalog_available ? 'ok' : 'error',
        status.message || 'YouTube Music status unavailable',
      );
      $('account-status').textContent = status.account_connected
        ? 'Connected with Google'
        : (status.message || 'Public catalogue available');
    } catch {
      setBadge($('home-yt-status'), 'error', 'Unable to check YouTube Music');
      $('account-status').textContent = 'Unable to check YouTube Music.';
    }
  }

  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  window.addEventListener('playlistmuse-settings-opened', refreshStatus);
  refreshStatus();
})();
