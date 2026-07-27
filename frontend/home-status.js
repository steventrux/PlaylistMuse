(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function setBadge(element, state, label, title) {
    element.classList.remove('pending', 'ok', 'warn', 'neutral', 'error');
    element.classList.add(state);
    element.textContent = label;
    element.title = title;
    element.setAttribute('aria-label', title);
  }

  async function refreshStatus() {
    setBadge($('home-ai-status'), 'pending', 'AI checking', 'Checking AI provider configuration');
    setBadge($('home-yt-status'), 'pending', 'YT checking', 'Checking YouTube Music connection');

    try {
      const response = await fetch('/api/settings');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const settings = await response.json();
      setBadge(
        $('home-ai-status'),
        settings.configured ? 'ok' : 'warn',
        settings.configured ? 'AI ready' : 'AI setup',
        settings.configured ? `AI configured: ${settings.model}` : 'AI provider configuration required',
      );
    } catch {
      setBadge($('home-ai-status'), 'error', 'AI error', 'Unable to check AI configuration');
    }

    try {
      const response = await fetch('/api/youtube/status');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();

      if (status.account_connected) {
        setBadge(
          $('home-yt-status'),
          'ok',
          'YT connected',
          'YouTube Music account connected',
        );
      } else if (status.catalog_available) {
        setBadge(
          $('home-yt-status'),
          'neutral',
          'YT public',
          'Public YouTube Music catalogue available; Google account not connected',
        );
      } else {
        setBadge(
          $('home-yt-status'),
          'error',
          'YT unavailable',
          status.message || 'YouTube Music unavailable',
        );
      }

      $('account-status').textContent = status.account_connected
        ? 'Connected with Google'
        : (status.catalog_available
          ? 'Public catalogue available · Google account not connected'
          : (status.message || 'YouTube Music unavailable'));
    } catch {
      setBadge($('home-yt-status'), 'error', 'YT error', 'Unable to check YouTube Music');
      $('account-status').textContent = 'Unable to check YouTube Music.';
    }
  }

  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  window.addEventListener('playlistmuse-settings-opened', refreshStatus);
  refreshStatus();
})();
