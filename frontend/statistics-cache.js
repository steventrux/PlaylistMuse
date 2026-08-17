(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

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

  function renderCache(payload) {
    const container = $('stats-cache-rows');
    const empty = $('stats-cache-empty');
    const active = (payload.caches || []).filter((cache) => cache.hits + cache.misses > 0);
    container.textContent = '';
    if (!active.length) {
      container.classList.add('hidden');
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    container.classList.remove('hidden');
    for (const cache of active) {
      const hitRate = cache.hit_rate === null || cache.hit_rate === undefined ? 0 : cache.hit_rate;
      const rateText = cache.hit_rate === null || cache.hit_rate === undefined
        ? 'n/a'
        : `${Math.round(cache.hit_rate * 100)}%`;
      container.append(barRow(
        cache.name,
        `${cache.hits} hits · ${cache.misses} misses · ${rateText}`,
        hitRate,
      ));
    }
  }

  async function loadCache() {
    try {
      const response = await fetch('/api/diagnostics/storage', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderCache(await response.json());
      $('stats-cache-status').classList.add('hidden');
      $('stats-cache-content').classList.remove('hidden');
    } catch (error) {
      $('stats-cache-status').textContent = error.message || 'Cache statistics are unavailable right now.';
      $('stats-cache-status').classList.add('error');
    }
  }

  void loadCache();
})();
