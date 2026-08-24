(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const {formatCount} = window.PlaylistMuseStatsRender;

  const ACCENTS = ['violet', 'magenta', 'cyan'];

  const PROVIDER_LABELS = {
    gemini: 'Google Gemini',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    openrouter_auto: 'OpenRouter Auto',
    openrouter_free: 'OpenRouter Free',
    ollama: 'Ollama',
    custom: 'Custom endpoint',
  };

  function providerLabel(provider) {
    if (provider.startsWith('custom:')) {
      return `Custom · ${provider.slice('custom:'.length)}`;
    }
    return PROVIDER_LABELS[provider] || provider;
  }

  function accentFor(index) {
    return ACCENTS[index % ACCENTS.length];
  }

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return 'n/a';
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
  }

  function formatPercent(value) {
    return value === null || value === undefined ? 'n/a' : `${value}%`;
  }

  const STAGE_LABELS = {
    ai_draft: 'AI draft generation',
    lastfm_prompt_discovery: 'Last.fm prompt discovery',
    lastfm_seed_discovery: 'Last.fm seed discovery',
    catalogue_resolution: 'Catalogue resolution (total)',
    youtube_resolution: 'YouTube resolution',
    metadata_validation: 'Metadata validation',
    energy_ordering: 'Sonic energy ordering',
  };

  function stageLabel(stage) {
    return STAGE_LABELS[stage] || stage;
  }

  function barRow(label, valueText, fraction) {
    const row = document.createElement('div');
    row.className = 'stats-bar-row';
    const labelEl = document.createElement('span');
    labelEl.className = 'stats-bar-label';
    labelEl.textContent = label;
    const track = document.createElement('div');
    track.className = 'stats-bar-track';
    const fill = document.createElement('div');
    fill.className = 'stats-bar-fill';
    fill.style.width = `${Math.max(4, Math.round(fraction * 100))}%`;
    track.append(fill);
    const value = document.createElement('span');
    value.className = 'stats-bar-value';
    value.textContent = valueText;
    row.append(labelEl, track, value);
    return row;
  }

  function renderStageBars(stageTimings, container) {
    const entries = Object.entries(stageTimings || {})
      .sort((a, b) => (b[1].avg_ms || 0) - (a[1].avg_ms || 0));
    container.textContent = '';
    if (!entries.length) {
      const empty = document.createElement('p');
      empty.className = 'field-hint';
      empty.textContent = 'No per-stage timing recorded yet.';
      container.append(empty);
      return;
    }
    const maxAvg = Math.max(...entries.map(([, summary]) => summary.avg_ms || 0), 1);
    for (const [stage, summary] of entries) {
      container.append(barRow(
        stageLabel(stage),
        `avg ${formatDuration(summary.avg_ms)}`,
        (summary.avg_ms || 0) / maxAvg,
      ));
    }
  }

  function errorBadges(breakdown, container) {
    container.textContent = '';
    const entries = Object.entries(breakdown || {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) {
      const empty = document.createElement('p');
      empty.className = 'field-hint';
      empty.textContent = 'No generation errors recorded.';
      container.append(empty);
      return;
    }
    for (const [label, count] of entries) {
      const badge = document.createElement('span');
      badge.className = 'stats-error-badge';
      badge.textContent = `${label} × ${count}`;
      container.append(badge);
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

  function renderProviderDetail(provider, stats, accent) {
    const detail = $('stats-provider-detail');
    detail.textContent = '';
    detail.dataset.accent = accent;

    const card = document.createElement('div');
    card.className = 'stats-section stats-provider-detail-card';

    const heading = document.createElement('h3');
    heading.textContent = provider === ALL_LABEL ? provider : providerLabel(provider);
    card.append(heading);

    const tiles = document.createElement('div');
    tiles.className = 'stats-hero-secondary stats-advanced-tiles';
    tiles.append(
      tile(formatDuration(stats.avg_generation_ms), 'Average generation time'),
      tile(formatDuration(stats.median_generation_ms), 'Median generation time'),
      tile(formatDuration(stats.p95_generation_ms), 'P95 generation time'),
      tile(stats.avg_track_count ?? 'n/a', 'Average tracks per playlist'),
      tile(
        stats.avg_complexity_score === null || stats.avg_complexity_score === undefined
          ? 'n/a'
          : `${stats.avg_complexity_score}/100`,
        'Average prompt complexity',
      ),
      tile(formatPercent(stats.tag_coverage_percent), 'Tag coverage'),
      tile(formatCount(stats.total_errors), 'Generation errors'),
    );
    card.append(tiles);

    const stageHeading = document.createElement('h4');
    stageHeading.textContent = 'Time per generation stage';
    const stageBars = document.createElement('div');
    stageBars.className = 'stats-bar-list';
    card.append(stageHeading, stageBars);
    renderStageBars(stats.stage_timings, stageBars);

    const errorsHeading = document.createElement('h4');
    errorsHeading.textContent = 'Generation errors';
    const errorsRow = document.createElement('div');
    errorsRow.className = 'stats-error-badges';
    card.append(errorsHeading, errorsRow);
    errorBadges(stats.error_breakdown, errorsRow);

    detail.append(card);
  }

  const ALL_LABEL = 'All';

  function selectProvider(entries, provider) {
    const index = entries.findIndex(([name]) => name === provider);
    if (index === -1) return;
    document.querySelectorAll('.stats-provider-tab').forEach((button) => {
      button.classList.toggle('active', button.dataset.provider === provider);
    });
    renderProviderDetail(provider, entries[index][1], accentFor(index));
  }

  function renderTabs(entries) {
    const tabs = $('stats-provider-tabs');
    tabs.textContent = '';
    entries.forEach(([provider, stats], index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'stats-provider-tab';
      button.dataset.accent = accentFor(index);
      button.dataset.provider = provider;
      const name = document.createElement('span');
      name.textContent = provider === ALL_LABEL ? provider : providerLabel(provider);
      const count = document.createElement('span');
      count.className = 'stats-provider-tab-count';
      count.textContent = formatCount(stats.playlist_count || 0);
      button.append(name, count);
      button.addEventListener('click', () => selectProvider(entries, provider));
      tabs.append(button);
    });
  }

  function renderNerd(nerd) {
    const tabs = $('stats-provider-tabs');
    const detail = $('stats-provider-detail');
    const empty = $('stats-provider-cards-empty');

    const providers = Object.entries(nerd.by_provider || {})
      .filter(([provider, stats]) => provider !== 'unknown' && (stats.playlist_count || 0) > 0)
      .sort(([, a], [, b]) => (b.playlist_count || 0) - (a.playlist_count || 0));

    if (!providers.length) {
      tabs.classList.add('hidden');
      detail.classList.add('hidden');
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    tabs.classList.remove('hidden');
    detail.classList.remove('hidden');

    const entries = providers.length > 1
      ? [[ALL_LABEL, nerd.totals || providers[0][1]], ...providers]
      : providers;
    renderTabs(entries);
    selectProvider(entries, entries[0][0]);
  }

  async function loadStats() {
    try {
      const data = await readJson(await fetch('/api/stats', {cache: 'no-store'}));
      renderNerd(data.nerd || {});
      $('stats-advanced-status').classList.add('hidden');
      $('stats-advanced-content').classList.remove('hidden');
    } catch (error) {
      $('stats-advanced-status').textContent = error.message || 'Statistics are unavailable right now.';
      $('stats-advanced-status').classList.add('error');
    }
  }

  void loadStats();
})();
