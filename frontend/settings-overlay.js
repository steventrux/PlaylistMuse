(() => {
  'use strict';

  const SECTIONS = new Set(['ai', 'youtube', 'lastfm']);
  let overlay = null;
  let frame = null;
  let closeButton = null;
  let lastFocusedElement = null;
  let requestedSection = 'ai';

  function normalizeSection(section) {
    return SECTIONS.has(section) ? section : 'ai';
  }

  function settingsFrameUrl(section) {
    const target = new URL('/static/settings.html', window.location.origin);
    target.searchParams.set('embedded', '1');
    target.searchParams.set('section', normalizeSection(section));
    return `${target.pathname}${target.search}`;
  }

  function selectFrameSection(section) {
    const select = frame?.contentWindow?.PlaylistMuseSettingsSelect;
    if (typeof select === 'function') select(section, {updateUrl: false});
  }

  function close() {
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('settings-overlay-open');
    window.dispatchEvent(new Event('playlistmuse-status-changed'));
    lastFocusedElement?.focus?.();
  }

  function createOverlay() {
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'playlistmuse-settings-overlay';
    overlay.className = 'settings-overlay';
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');

    const dialog = document.createElement('div');
    dialog.className = 'settings-overlay-dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-label', 'PlaylistMuse settings');

    closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'secondary settings-icon-btn settings-overlay-close';
    closeButton.setAttribute('aria-label', 'Close settings');
    closeButton.title = 'Close settings';
    closeButton.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="m6 6 12 12M18 6 6 18" />
      </svg>
    `;

    frame = document.createElement('iframe');
    frame.className = 'settings-overlay-frame';
    frame.title = 'PlaylistMuse Settings';
    frame.setAttribute('loading', 'eager');

    frame.addEventListener('load', () => {
      frame.dataset.ready = 'true';
      selectFrameSection(requestedSection);
    });

    closeButton.addEventListener('click', close);
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) close();
    });

    dialog.append(closeButton, frame);
    overlay.append(dialog);
    document.body.append(overlay);

    window.addEventListener('message', (event) => {
      if (event.origin !== window.location.origin || event.source !== frame?.contentWindow) return;
      if (event.data?.type === 'playlistmuse-settings-close') close();
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && overlay && !overlay.hidden) close();
    });

    return overlay;
  }

  function open(section = 'ai') {
    requestedSection = normalizeSection(section);
    createOverlay();

    lastFocusedElement = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('settings-overlay-open');

    if (!frame.dataset.initialized) {
      frame.dataset.initialized = 'true';
      frame.src = settingsFrameUrl(requestedSection);
    } else if (frame.dataset.ready === 'true') {
      selectFrameSection(requestedSection);
    }

    closeButton.focus();
  }

  window.PlaylistMuseSettingsOverlay = Object.freeze({open, close});
})();
