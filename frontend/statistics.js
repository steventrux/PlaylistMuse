(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const {formatCount, renderRankList} = window.PlaylistMuseStatsRender;

  const OVERVIEW_LIMIT = 5;
  const monthFormatter = new Intl.DateTimeFormat('en-US', {month: 'short'});

  function formatMonth(key) {
    const [year, month] = String(key).split('-').map(Number);
    if (!year || !month) return key;
    return monthFormatter.format(new Date(Date.UTC(year, month - 1, 1)));
  }

  function top(items) {
    return (items || []).slice(0, OVERVIEW_LIMIT);
  }

  function renderTimeline(monthly) {
    const container = $('stats-timeline');
    if (!container) return;
    container.replaceChildren();

    const entries = Object.entries(monthly || {});
    const empty = $('stats-timeline-empty');
    empty?.classList.toggle('hidden', entries.length > 0);
    container.classList.toggle('hidden', entries.length === 0);
    if (!entries.length) return;

    const max = Math.max(1, ...entries.map(([, count]) => count));

    entries.forEach(([key, count]) => {
      const col = document.createElement('div');
      col.className = 'stats-timeline-col';
      col.title = `${formatMonth(key)}: ${formatCount(count)} playlist${count === 1 ? '' : 's'}`;

      const bar = document.createElement('div');
      bar.className = 'stats-timeline-bar';
      // Reserve space for the month label + gap below the bar (see .stats-timeline-col
      // in statistics.css) so a 100%-of-max bar never overflows the card and gets
      // clipped at the top.
      const ratio = Math.max(0.03, count / max);
      bar.style.height = `calc((100% - 20px) * ${ratio})`;

      const month = document.createElement('span');
      month.className = 'stats-timeline-month';
      month.textContent = formatMonth(key);

      col.append(bar, month);
      container.append(col);
    });
  }

  function renderGeneral(general) {
    $('stat-total-generated').textContent = formatCount(general.total_generated);
    $('stat-total-saved').textContent = formatCount(general.total_saved);
    $('stat-total-published').textContent = formatCount(general.total_published);

    renderTimeline(general.playlists_by_month);
    renderRankList('stats-artist-list', 'stats-artist-list-empty', top(general.top_artists));
    renderRankList('stats-genre-chips', 'stats-genre-chips-empty', top(general.top_genres));
    renderRankList('stats-mood-chips', 'stats-mood-chips-empty', top(general.top_moods));
    renderRankList('stats-period-chips', 'stats-period-chips-empty', top(general.top_periods));
  }

  async function loadStats() {
    try {
      const data = await readJson(await fetch('/api/stats', {cache: 'no-store'}));
      renderGeneral(data.general || {});
      $('stats-status').classList.add('hidden');
      $('stats-content').classList.remove('hidden');
    } catch (error) {
      $('stats-status').textContent = error.message || 'Statistics are unavailable right now.';
      $('stats-status').classList.add('error');
    }
  }

  function setTelemetryStatus(text, state = '') {
    const status = $('telemetry-status');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('hidden', !text);
    status.classList.toggle('ok', state === 'ok');
    status.classList.toggle('error', state === 'error');
  }

  function setToggleChecked(toggle, checked) {
    toggle.setAttribute('aria-checked', String(checked));
  }

  async function loadTelemetrySetting() {
    const toggle = $('telemetry-toggle');
    if (!toggle) return;
    try {
      const data = await readJson(await fetch('/api/telemetry/settings', {cache: 'no-store'}));
      setToggleChecked(toggle, Boolean(data.enabled));
    } catch {
      // Leave the toggle at its default (off) if the setting can't be read.
    }
  }

  async function saveTelemetrySetting(toggle) {
    const next = toggle.getAttribute('aria-checked') !== 'true';
    setToggleChecked(toggle, next);
    try {
      const data = await readJson(await fetch('/api/telemetry/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: next}),
      }));
      setToggleChecked(toggle, Boolean(data.enabled));
      setTelemetryStatus(data.enabled ? 'Contributing to the public counter.' : 'Not sharing usage statistics.', 'ok');
    } catch (error) {
      setToggleChecked(toggle, !next);
      setTelemetryStatus(error.message || 'The setting could not be saved.', 'error');
    }
  }

  $('telemetry-toggle')?.addEventListener('click', (event) => {
    void saveTelemetrySetting(event.currentTarget);
  });

  void loadStats();
  void loadTelemetrySetting();
})();
