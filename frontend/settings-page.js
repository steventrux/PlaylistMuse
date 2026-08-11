(() => {
  'use strict';

  const SECTIONS = new Set(['ai', 'youtube', 'lastfm', 'support']);
  const sectionTitles = {
    ai: 'AI',
    youtube: 'YouTube Music',
    lastfm: 'Last.fm',
    support: 'Diagnostics',
  };
  const sectionEyebrows = {
    ai: 'Integration',
    youtube: 'Integration',
    lastfm: 'Integration',
    support: 'Support',
  };

  const $ = (id) => document.getElementById(id);
  const query = new URLSearchParams(window.location.search);
  const embedded = query.get('embedded') === '1' && window.parent !== window;

  function safeReturnTarget() {
    const raw = query.get('return') || '/';
    if (!raw.startsWith('/') || raw.startsWith('//')) return '/';
    if (raw.startsWith('/static/settings.html')) return '/';
    return raw;
  }

  function requestedSection() {
    const value = query.get('section') || 'ai';
    return SECTIONS.has(value) ? value : 'ai';
  }

  function updateLocation(section) {
    if (embedded) return;
    const url = new URL(window.location.href);
    url.searchParams.set('section', section);
    if (!url.searchParams.has('return')) url.searchParams.set('return', safeReturnTarget());
    window.history.replaceState({settingsSection: section}, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function sectionPanel(section) {
    if (section === 'ai') return $('setup-ai-step');
    if (section === 'youtube') return $('setup-youtube-step');
    if (section === 'lastfm') return $('settings-lastfm-host');
    return $('settings-support-panel');
  }

  function notifySectionOpened(section) {
    const eventName = {
      ai: 'playlistmuse-ai-settings-opened',
      youtube: 'playlistmuse-youtube-settings-opened',
      lastfm: 'playlistmuse-lastfm-settings-opened',
    }[section];
    if (eventName) window.dispatchEvent(new Event(eventName));
  }

  function selectSection(section, {updateUrl = true} = {}) {
    const selected = SECTIONS.has(section) ? section : 'ai';

    SECTIONS.forEach((name) => {
      const panel = sectionPanel(name);
      panel?.classList.toggle('hidden', name !== selected);
      panel?.setAttribute('aria-hidden', String(name !== selected));
    });

    document.querySelectorAll('[data-settings-section]').forEach((button) => {
      const active = button.dataset.settingsSection === selected;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });

    const title = sectionTitles[selected] || sectionTitles.ai;
    $('settings-section-title').textContent = title;
    $('settings-section-eyebrow').textContent = sectionEyebrows[selected] || 'Integration';
    document.title = `${title} Settings · PlaylistMuse`;
    if (updateUrl) updateLocation(selected);
    notifySectionOpened(selected);
  }

  function closeSettings() {
    if (embedded) {
      window.parent.postMessage({type: 'playlistmuse-settings-close'}, window.location.origin);
      return;
    }
    window.location.assign(safeReturnTarget());
  }

  document.querySelectorAll('[data-settings-section]').forEach((button) => {
    button.addEventListener('click', () => selectSection(button.dataset.settingsSection));
  });

  $('settings-close')?.addEventListener('click', closeSettings);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSettings();
  });

  window.PlaylistMuseSettingsSelect = selectSection;
  selectSection(requestedSection(), {updateUrl: false});
})();