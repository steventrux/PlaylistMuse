(() => {
  'use strict';

  /* The home page needs this small companion because home-status.js leaves
   * Last.fm availability to the seed controls there. Other pages already
   * refresh the same indicator through home-status.js and must not duplicate
   * the API request. */
  if (!document.getElementById('setup-dialog')) return;

  const INDICATOR_STATES = ['pending', 'on', 'off', 'error'];

  function setState(element, state, tooltip) {
    if (!element) return;
    element.classList.remove(...INDICATOR_STATES);
    element.classList.add(state);
    element.dataset.tooltip = tooltip;
    element.title = tooltip;
    element.setAttribute('aria-label', tooltip);
  }

  function publishAvailability(configured) {
    window.dispatchEvent(new CustomEvent('playlistmuse-lastfm-status', {
      detail: {configured: Boolean(configured)},
    }));
  }

  async function refreshStatus() {
    const indicator = document.getElementById('header-lastfm-status');
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
      publishAvailability(configured);
    } catch {
      setState(
        indicator,
        'error',
        'Unable to check Last.fm configuration · click to open Last.fm Settings',
      );
      publishAvailability(false);
    }
  }

  window.addEventListener('playlistmuse-status-changed', () => void refreshStatus());
  void refreshStatus();
})();
