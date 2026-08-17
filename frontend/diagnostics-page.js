(() => {
  'use strict';

  const SECTIONS = new Set(['bugs', 'storage']);
  const sectionTitles = {bugs: 'Bug reports', storage: 'Storage'};

  const $ = (id) => document.getElementById(id);
  const query = new URLSearchParams(window.location.search);

  function requestedSection() {
    const value = query.get('section') || 'bugs';
    return SECTIONS.has(value) ? value : 'bugs';
  }

  function updateLocation(section) {
    const url = new URL(window.location.href);
    url.searchParams.set('section', section);
    window.history.replaceState({diagnosticsSection: section}, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function sectionPanel(section) {
    return section === 'storage' ? $('diagnostics-storage-panel') : $('diagnostics-bugs-panel');
  }

  function selectSection(section, {updateUrl = true} = {}) {
    const selected = SECTIONS.has(section) ? section : 'bugs';

    SECTIONS.forEach((name) => {
      const panel = sectionPanel(name);
      panel?.classList.toggle('hidden', name !== selected);
      panel?.setAttribute('aria-hidden', String(name !== selected));
    });

    document.querySelectorAll('[data-diagnostics-section]').forEach((button) => {
      const active = button.dataset.diagnosticsSection === selected;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });

    const title = sectionTitles[selected] || sectionTitles.bugs;
    $('diagnostics-section-title').textContent = title;
    document.title = `${title} · Diagnostics · PlaylistMuse`;
    if (updateUrl) updateLocation(selected);
  }

  document.querySelectorAll('[data-diagnostics-section]').forEach((button) => {
    button.addEventListener('click', () => selectSection(button.dataset.diagnosticsSection));
  });

  selectSection(requestedSection(), {updateUrl: false});
})();
