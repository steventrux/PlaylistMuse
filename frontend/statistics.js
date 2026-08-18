(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const {formatCount} = window.PlaylistMuseStatsRender;

  const OVERVIEW_LIMIT = 5;
  const monthFormatter = new Intl.DateTimeFormat('en-US', {month: 'short'});

  const RANKINGS = [
    {key: 'artists', containerId: 'stats-artist-list', emptyId: 'stats-artist-list-empty', toggleId: 'stats-artist-list-toggle'},
    {key: 'genres', containerId: 'stats-genre-chips', emptyId: 'stats-genre-chips-empty', toggleId: 'stats-genre-chips-toggle'},
    {key: 'moods', containerId: 'stats-mood-chips', emptyId: 'stats-mood-chips-empty', toggleId: 'stats-mood-chips-toggle'},
    {key: 'periods', containerId: 'stats-period-chips', emptyId: 'stats-period-chips-empty', toggleId: 'stats-period-chips-toggle'},
    {key: 'customTags', containerId: 'stats-custom-tag-list', emptyId: 'stats-custom-tag-list-empty', toggleId: 'stats-custom-tag-list-toggle'},
  ];
  const rankingState = new Map(RANKINGS.map((ranking) => [ranking.key, {full: [], expanded: false}]));

  function formatMonth(key) {
    const [year, month] = String(key).split('-').map(Number);
    if (!year || !month) return key;
    return monthFormatter.format(new Date(Date.UTC(year, month - 1, 1)));
  }

  function top(items) {
    return (items || []).slice(0, OVERVIEW_LIMIT);
  }

  const TIMELINE_TICKS = 4;

  function renderTimelineAxis(max) {
    const yAxis = $('stats-timeline-yaxis');
    if (!yAxis) return;
    yAxis.replaceChildren();
    for (let tick = TIMELINE_TICKS; tick >= 0; tick--) {
      const label = document.createElement('span');
      label.className = 'stats-timeline-axis-label';
      label.textContent = formatCount(Math.round((max / TIMELINE_TICKS) * tick));
      yAxis.append(label);
    }
  }

  function renderTimelineGridlines(container) {
    for (let tick = 0; tick <= TIMELINE_TICKS; tick++) {
      const line = document.createElement('div');
      line.className = 'stats-timeline-gridline';
      if (tick === 0) line.classList.add('stats-timeline-gridline-baseline');
      // Same "reserve 20px for the month label" offset the bars use below, so
      // gridlines land exactly level with the bar heights they annotate.
      line.style.bottom = `calc(20px + (100% - 20px) * ${tick / TIMELINE_TICKS})`;
      container.append(line);
    }
  }

  function renderTimeline(monthly) {
    const container = $('stats-timeline');
    if (!container) return;
    container.replaceChildren();

    const entries = Object.entries(monthly || {});
    const empty = $('stats-timeline-empty');
    const chart = $('stats-timeline-chart');
    empty?.classList.toggle('hidden', entries.length > 0);
    chart?.classList.toggle('hidden', entries.length === 0);
    if (!entries.length) return;

    const max = Math.max(1, ...entries.map(([, count]) => count));
    renderTimelineAxis(max);
    renderTimelineGridlines(container);

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

  function renderBarRanking(containerId, emptyId, items) {
    const container = $(containerId);
    const empty = $(emptyId);
    container.textContent = '';
    if (!items.length) {
      container.classList.add('hidden');
      empty?.classList.remove('hidden');
      return;
    }
    empty?.classList.add('hidden');
    container.classList.remove('hidden');

    const max = Math.max(...items.map((item) => item.count || 0), 1);
    for (const item of items) {
      const row = document.createElement('div');
      row.className = 'stats-bar-row';
      const label = document.createElement('span');
      label.className = 'stats-bar-label';
      label.textContent = item.label;
      const track = document.createElement('div');
      track.className = 'stats-bar-track';
      const fill = document.createElement('div');
      fill.className = 'stats-bar-fill';
      fill.style.width = `${Math.max(4, Math.round((item.count / max) * 100))}%`;
      track.append(fill);
      const value = document.createElement('span');
      value.className = 'stats-bar-value';
      value.textContent = formatCount(item.count);
      row.append(label, track, value);
      container.append(row);
    }
  }

  function renderRanking(ranking, full) {
    const state = rankingState.get(ranking.key);
    state.full = full;
    const items = state.expanded ? full : top(full);
    renderBarRanking(ranking.containerId, ranking.emptyId, items);

    const toggle = $(ranking.toggleId);
    if (!toggle) return;
    if (full.length <= OVERVIEW_LIMIT) {
      toggle.classList.add('hidden');
      return;
    }
    toggle.classList.remove('hidden');
    toggle.textContent = state.expanded ? 'Show less ↑' : `See all ${formatCount(full.length)} →`;
  }

  function toggleRanking(ranking) {
    const state = rankingState.get(ranking.key);
    state.expanded = !state.expanded;
    renderRanking(ranking, state.full);
  }

  for (const ranking of RANKINGS) {
    $(ranking.toggleId)?.addEventListener('click', () => toggleRanking(ranking));
  }

  const RANKING_SOURCE = {
    artists: 'top_artists',
    genres: 'top_genres',
    moods: 'top_moods',
    periods: 'top_periods',
    customTags: 'top_custom_tags',
  };

  function renderGeneral(general) {
    $('stat-total-generated').textContent = formatCount(general.total_generated);
    $('stat-total-saved').textContent = formatCount(general.total_saved);
    $('stat-total-published').textContent = formatCount(general.total_published);
    $('stat-total-artists').textContent = formatCount((general.top_artists || []).length);
    $('stat-total-genres').textContent = formatCount((general.top_genres || []).length);
    $('stat-total-moods').textContent = formatCount((general.top_moods || []).length);
    $('stat-total-periods').textContent = formatCount((general.top_periods || []).length);

    renderTimeline(general.playlists_by_month);
    for (const ranking of RANKINGS) {
      renderRanking(ranking, general[RANKING_SOURCE[ranking.key]] || []);
    }
  }

  async function loadStats() {
    try {
      const data = await readJson(await fetch('/api/stats', {cache: 'no-store'}));
      renderGeneral(data.general || {});
      $('stats-status').classList.add('hidden');
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
