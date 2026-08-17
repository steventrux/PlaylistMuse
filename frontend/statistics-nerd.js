(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const {formatCount, renderRankList} = window.PlaylistMuseStatsRender;

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
  }

  function formatPercent(value) {
    return value === null || value === undefined ? '—' : `${value}%`;
  }

  const STAGE_LABELS = {
    ai_draft: 'AI draft generation',
    lastfm_prompt_discovery: 'Last.fm prompt discovery',
    lastfm_seed_discovery: 'Last.fm seed discovery',
    catalogue_resolution: 'Catalogue resolution (total)',
    youtube_resolution: 'YouTube resolution',
    metadata_validation: 'Metadata validation',
  };

  function stageLabel(stage) {
    return STAGE_LABELS[stage] || stage;
  }

  function renderStageTimings(stageTimings) {
    const container = $('stats-stage-timings');
    const empty = $('stats-stage-timings-empty');
    const entries = Object.entries(stageTimings || {});
    container.textContent = '';
    if (!entries.length) {
      container.classList.add('hidden');
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    container.classList.remove('hidden');
    for (const [stage, summary] of entries) {
      const row = document.createElement('div');
      row.className = 'stats-stage-row';
      const label = document.createElement('span');
      label.className = 'stats-stage-row-label';
      label.textContent = stageLabel(stage);
      const value = document.createElement('span');
      value.className = 'stats-stage-row-value';
      value.textContent =
        `avg ${formatDuration(summary.avg_ms)} · median ${formatDuration(summary.median_ms)} · p95 ${formatDuration(summary.p95_ms)}`;
      row.append(label, value);
      container.append(row);
    }
  }

  function renderNerd(nerd) {
    $('stat-avg-duration').textContent = formatDuration(nerd.avg_generation_ms);
    $('stat-median-duration').textContent = formatDuration(nerd.median_generation_ms);
    $('stat-p95-duration').textContent = formatDuration(nerd.p95_generation_ms);
    $('stat-avg-tracks').textContent = nerd.avg_track_count ?? '—';
    $('stat-tag-coverage').textContent = formatPercent(nerd.tag_coverage_percent);
    $('stat-total-errors').textContent = formatCount(nerd.total_errors);

    const providers = Object.entries(nerd.provider_breakdown || {})
      .map(([label, count]) => ({label, count}))
      .sort((a, b) => b.count - a.count);
    renderRankList('stats-provider-breakdown', null, providers);

    const errors = Object.entries(nerd.error_breakdown || {})
      .map(([label, count]) => ({label, count}))
      .sort((a, b) => b.count - a.count);
    renderRankList('stats-error-breakdown', 'stats-error-breakdown-empty', errors);

    renderStageTimings(nerd.stage_timings);
  }

  async function loadStats() {
    try {
      const data = await readJson(await fetch('/api/stats', {cache: 'no-store'}));
      renderNerd(data.nerd || {});
      $('stats-status').classList.add('hidden');
      $('stats-content').classList.remove('hidden');
    } catch (error) {
      $('stats-status').textContent = error.message || 'Statistics are unavailable right now.';
      $('stats-status').classList.add('error');
    }
  }

  void loadStats();
})();
