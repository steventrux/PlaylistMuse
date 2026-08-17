(() => {
  'use strict';

  const status = document.getElementById('storage-status');
  const breakdown = document.getElementById('storage-breakdown');
  const clearButton = document.getElementById('clear-cache');
  if (!status || !breakdown) return;

  const databaseValue = document.getElementById('storage-database');
  const logsValue = document.getElementById('storage-logs');
  const cacheValue = document.getElementById('storage-cache');
  const totalValue = document.getElementById('storage-total');
  const cacheNote = document.getElementById('storage-cache-note');
  const cacheMetrics = document.getElementById('storage-cache-metrics');

  function formatBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value < 1024) return `${value} B`;
    const units = ['KB', 'MB', 'GB'];
    let scaled = value / 1024;
    let unitIndex = 0;
    while (scaled >= 1024 && unitIndex < units.length - 1) {
      scaled /= 1024;
      unitIndex += 1;
    }
    return `${scaled.toFixed(scaled >= 10 ? 0 : 1)} ${units[unitIndex]}`;
  }

  function renderCacheNote(payload) {
    if (!cacheNote) return;
    const usage = payload.usage || {};
    const base = "Caches already clean themselves up automatically every hour, removing expired entries. Clearing manually is rarely needed.";
    if (usage.estimate_reliable) {
      const generations = usage.total_generations || 0;
      const days = usage.days_active || 0;
      const estimate = formatBytes(payload.caches_estimated_steady_state_total_bytes);
      cacheNote.textContent =
        `${base} Based on this installation's actual usage (${generations} generation${generations === 1 ? '' : 's'} over ${days} day${days === 1 ? '' : 's'}), total cache size should level off around ${estimate}.`;
    } else {
      cacheNote.textContent = `${base} A few more days of usage are needed before a reliable size estimate can be shown.`;
    }
    cacheNote.classList.remove('hidden');
  }

  function renderCacheMetrics(caches) {
    if (!cacheMetrics) return;
    const active = (caches || []).filter((cache) => cache.hits + cache.misses > 0);
    cacheMetrics.textContent = '';
    if (!active.length) {
      cacheMetrics.classList.add('hidden');
      return;
    }
    for (const cache of active) {
      const row = document.createElement('div');
      row.className = 'storage-cache-metrics-row';
      const label = document.createElement('span');
      label.className = 'storage-cache-metrics-row-label';
      label.textContent = cache.name;
      const value = document.createElement('span');
      value.className = 'storage-cache-metrics-row-value';
      const hitRate = cache.hit_rate === null || cache.hit_rate === undefined
        ? 'n/a'
        : `${Math.round(cache.hit_rate * 100)}%`;
      value.textContent = `${cache.hits} hits · ${cache.misses} misses · ${hitRate} hit rate`;
      row.append(label, value);
      cacheMetrics.append(row);
    }
    cacheMetrics.classList.remove('hidden');
  }

  function renderStorage(payload) {
    const database = payload.database || {};
    databaseValue.textContent =
      `${formatBytes(database.size_bytes)} · ${database.playlist_count || 0} playlists · ${database.track_count || 0} tracks`;
    logsValue.textContent = formatBytes((payload.logs || {}).size_bytes);
    const cacheCount = Array.isArray(payload.caches) ? payload.caches.length : 0;
    cacheValue.textContent = `${formatBytes(payload.caches_total_bytes)} · ${cacheCount} files`;
    totalValue.textContent = formatBytes(payload.data_dir_total_bytes);
    breakdown.classList.remove('hidden');
    renderCacheNote(payload);
    renderCacheMetrics(payload.caches);
    status.textContent = 'Storage usage';
    status.classList.remove('error');
  }

  async function loadStorage() {
    try {
      const response = await fetch('/api/diagnostics/storage', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderStorage(await response.json());
    } catch {
      status.textContent = 'Storage usage is unavailable.';
      status.classList.add('error');
      breakdown.classList.add('hidden');
      if (cacheNote) cacheNote.classList.add('hidden');
      if (cacheMetrics) cacheMetrics.classList.add('hidden');
    }
  }

  async function clearCache() {
    if (!window.confirm("Clear PlaylistMuse's cached lookups? This does not delete any saved playlists.")) return;
    clearButton.disabled = true;
    const originalLabel = clearButton.textContent;
    clearButton.textContent = 'Clearing…';
    try {
      const response = await fetch('/api/diagnostics/storage/clear-cache', {method: 'POST'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderStorage(await response.json());
    } catch {
      status.textContent = 'Could not clear the cache.';
      status.classList.add('error');
    } finally {
      clearButton.disabled = false;
      clearButton.textContent = originalLabel;
    }
  }

  if (clearButton) clearButton.addEventListener('click', clearCache);

  loadStorage();
})();
