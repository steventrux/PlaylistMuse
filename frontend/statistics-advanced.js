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

  function slugify(value) {
    return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
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

  function renderStageTimings(stageTimings, containerId, emptyId) {
    const container = $(containerId);
    const empty = $(emptyId);
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

  function tile(value, label) {
    const wrap = document.createElement('div');
    wrap.className = 'stats-secondary-stat';
    const valueEl = document.createElement('span');
    valueEl.className = 'stats-secondary-value';
    valueEl.textContent = value;
    const labelEl = document.createElement('span');
    labelEl.className = 'stats-secondary-label';
    labelEl.textContent = label;
    wrap.append(valueEl, labelEl);
    return wrap;
  }

  function renderProviderCard(provider, stats, container) {
    // Built and appended to `container` before the stage-timing/error-list content is
    // filled in, since renderStageTimings()/renderRankList() look their targets up via
    // document.getElementById() -- which only finds nodes already attached to the live
    // document, not ones still sitting in a detached DOM fragment.
    const slug = slugify(provider);
    const card = document.createElement('div');
    card.className = 'stats-section stats-provider-card';

    const heading = document.createElement('h3');
    const name = document.createElement('span');
    name.textContent = provider;
    const count = document.createElement('span');
    count.className = 'stats-section-cta';
    const playlists = stats.playlist_count || 0;
    count.textContent = `${formatCount(playlists)} playlist${playlists === 1 ? '' : 's'}`;
    heading.append(name, count);
    card.append(heading);

    const tiles = document.createElement('div');
    tiles.className = 'stats-hero-secondary stats-advanced-tiles';
    tiles.append(
      tile(formatDuration(stats.avg_generation_ms), 'Average generation time'),
      tile(formatDuration(stats.median_generation_ms), 'Median generation time'),
      tile(formatDuration(stats.p95_generation_ms), 'P95 generation time'),
      tile(stats.avg_track_count ?? '—', 'Average tracks per playlist'),
      tile(formatPercent(stats.tag_coverage_percent), 'Tag coverage'),
      tile(formatCount(stats.total_errors), 'Generation errors'),
    );
    card.append(tiles);

    const stageHeading = document.createElement('h4');
    stageHeading.textContent = 'Time per generation stage';
    const stageContainer = document.createElement('div');
    stageContainer.className = 'stats-stage-timings';
    stageContainer.id = `stats-stage-timings-${slug}`;
    const stageEmpty = document.createElement('p');
    stageEmpty.className = 'field-hint hidden';
    stageEmpty.id = `stats-stage-timings-${slug}-empty`;
    stageEmpty.textContent = 'No per-stage timing recorded yet.';
    card.append(stageHeading, stageContainer, stageEmpty);

    const errorsHeading = document.createElement('h4');
    errorsHeading.textContent = 'Generation errors';
    const errorsList = document.createElement('ol');
    errorsList.className = 'stats-rank-list';
    errorsList.id = `stats-error-breakdown-${slug}`;
    const errorsEmpty = document.createElement('p');
    errorsEmpty.className = 'field-hint hidden';
    errorsEmpty.id = `stats-error-breakdown-${slug}-empty`;
    errorsEmpty.textContent = 'No generation errors recorded.';
    card.append(errorsHeading, errorsList, errorsEmpty);

    container.append(card);

    renderStageTimings(stats.stage_timings, stageContainer.id, stageEmpty.id);
    const errors = Object.entries(stats.error_breakdown || {})
      .map(([label, errorCount]) => ({label, count: errorCount}))
      .sort((a, b) => b.count - a.count);
    renderRankList(errorsList.id, errorsEmpty.id, errors);
  }

  function renderNerd(nerd) {
    const container = $('stats-provider-cards');
    const empty = $('stats-provider-cards-empty');
    container.textContent = '';

    const providers = Object.entries(nerd.by_provider || {})
      .sort(([, a], [, b]) => (b.playlist_count || 0) - (a.playlist_count || 0));

    if (!providers.length) {
      container.classList.add('hidden');
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    container.classList.remove('hidden');
    for (const [provider, stats] of providers) {
      renderProviderCard(provider, stats, container);
    }
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
