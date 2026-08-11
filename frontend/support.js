(() => {
  'use strict';

  const target = document.getElementById('support-build-info');
  if (!target) return;

  async function loadBuildInfo() {
    try {
      const response = await fetch('/api/version', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const info = await response.json();
      const parts = [info.display || info.version || 'Version unavailable'];
      if (info.channel) parts.push(info.channel);
      if (info.commit) parts.push(info.commit);
      target.textContent = `Running build: ${parts.join(' · ')}`;
    } catch {
      target.textContent = 'Running build information is unavailable.';
    }
  }

  loadBuildInfo();
})();
