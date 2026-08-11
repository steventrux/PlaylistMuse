(() => {
  'use strict';

  const target = document.getElementById('support-build-info');
  const bugLink = document.getElementById('report-bug');
  if (!target) return;

  const ISSUE_URL = 'https://github.com/steventrux/PlaylistMuse/issues/new';
  const STABLE_TEMPLATE_URL = `${ISSUE_URL}?template=bug_report.yml`;

  function developmentBugReportUrl(build) {
    const url = new URL(ISSUE_URL);
    url.searchParams.set('title', '[Bug] ');
    url.searchParams.set('body', [
      '## What happened?',
      '<!-- Describe the problem and where you encountered it. -->',
      '',
      '## Steps to reproduce',
      '1. ',
      '',
      '## Expected behavior',
      '<!-- What did you expect PlaylistMuse to do? -->',
      '',
      '## Actual behavior',
      '<!-- What did PlaylistMuse do instead? -->',
      '',
      '## Running build',
      build,
      '',
      '## Browser and operating system',
      '<!-- Example: Chrome on Android, Firefox on Linux. -->',
      '',
      '## Error reference',
      '<!-- Paste the PM-... reference here if PlaylistMuse displayed one. -->',
      '',
      '## Diagnostic report',
      '<!-- Attach the ZIP downloaded from Settings → Diagnostics if available. -->',
      '',
      '## Additional context or screenshots',
      '',
      '> Do not include API keys, passwords, OAuth tokens, cookies, .env files, or raw credential/configuration files.',
    ].join('\n'));
    return url.toString();
  }

  async function loadBuildInfo() {
    try {
      const response = await fetch('/api/version', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const info = await response.json();
      const display = info.display || info.version || 'Version unavailable';
      target.textContent = `Running build: ${display}`;
      if (bugLink) {
        bugLink.href = info.channel === 'stable'
          ? STABLE_TEMPLATE_URL
          : developmentBugReportUrl(display);
      }
    } catch {
      target.textContent = 'Running build information is unavailable.';
      if (bugLink) bugLink.href = STABLE_TEMPLATE_URL;
    }
  }

  loadBuildInfo();
})();
