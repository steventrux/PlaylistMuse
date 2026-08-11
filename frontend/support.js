(() => {
  'use strict';

  const target = document.getElementById('support-build-info');
  if (!target) return;

  async function loadBuildInfo() {
    try {
      const response = await fetch('/api/version', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const info = await response.json();
      target.textContent = `Running build: ${info.display || info.version || 'Version unavailable'}`;
    } catch {
      target.textContent = 'Running build information is unavailable.';
    }
  }

  loadBuildInfo();
})();
