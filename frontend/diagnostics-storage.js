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

  function renderStorage(payload) {
    const database = payload.database || {};
    databaseValue.textContent =
      `${formatBytes(database.size_bytes)} · ${database.playlist_count || 0} playlists · ${database.track_count || 0} tracks`;
    logsValue.textContent = formatBytes((payload.logs || {}).size_bytes);
    const cacheCount = Array.isArray(payload.caches) ? payload.caches.length : 0;
    cacheValue.textContent = `${formatBytes(payload.caches_total_bytes)} · ${cacheCount} files`;
    totalValue.textContent = formatBytes(payload.data_dir_total_bytes);
    breakdown.classList.remove('hidden');
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
