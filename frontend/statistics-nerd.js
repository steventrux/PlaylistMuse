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
