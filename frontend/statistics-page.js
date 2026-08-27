(() => {
  'use strict';

  const SECTIONS = new Set(['overview', 'timeline', 'artists', 'genres', 'moods', 'periods', 'tags', 'taste', 'advanced', 'cache']);
  const sectionTitles = {
    overview: 'Overview',
    timeline: 'Timeline',
    artists: 'Top artists',
    genres: 'Top genres',
    moods: 'Top moods',
    periods: 'Top periods',
    tags: 'Personal tags',
    taste: 'Taste memory',
    advanced: 'AI performance',
    cache: 'Cache',
  };
  const sectionEyebrows = {
    overview: 'Music',
    timeline: 'Music',
    artists: 'Music',
    genres: 'Music',
    moods: 'Music',
    periods: 'Music',
    tags: 'Music',
    taste: 'Music',
    advanced: 'Technical',
    cache: 'Technical',
  };

  const $ = (id) => document.getElementById(id);
  const query = new URLSearchParams(window.location.search);

  function requestedSection() {
    const value = query.get('section') || 'overview';
    return SECTIONS.has(value) ? value : 'overview';
  }

  function updateLocation(section) {
    const url = new URL(window.location.href);
    url.searchParams.set('section', section);
    window.history.replaceState({statsSection: section}, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function sectionPanel(section) {
    return $(`stats-${section}-panel`);
  }

  function selectSection(section, {updateUrl = true} = {}) {
    const selected = SECTIONS.has(section) ? section : 'overview';

    SECTIONS.forEach((name) => {
      const panel = sectionPanel(name);
      panel?.classList.toggle('hidden', name !== selected);
      panel?.setAttribute('aria-hidden', String(name !== selected));
    });

    document.querySelectorAll('[data-stats-section]').forEach((button) => {
      const active = button.dataset.statsSection === selected;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });

    const title = sectionTitles[selected] || sectionTitles.overview;
    $('stats-section-title').textContent = title;
    $('stats-section-eyebrow').textContent = sectionEyebrows[selected] || sectionEyebrows.overview;
    document.title = `${title} · Statistics · PlaylistMuse`;
    if (updateUrl) updateLocation(selected);
  }

  document.querySelectorAll('[data-stats-section]').forEach((button) => {
    button.addEventListener('click', () => selectSection(button.dataset.statsSection));
  });

  selectSection(requestedSection(), {updateUrl: false});
})();
