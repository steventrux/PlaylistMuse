(() => {
  'use strict';

  if (window.PlaylistMuseDiagnosticsClientInstalled) return;
  window.PlaylistMuseDiagnosticsClientInstalled = true;

  const ENDPOINT = '/api/diagnostics/frontend-error';

  function cleanSource(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    try {
      const url = new URL(text, window.location.origin);
      return url.origin === window.location.origin ? url.pathname : `${url.origin}${url.pathname}`;
    } catch {
      return text.split('?')[0].slice(0, 500);
    }
  }

  function report(payload) {
    const message = String(payload?.message || '').trim();
    if (!message) return;

    const body = {
      message: message.slice(0, 1200),
      source: cleanSource(payload?.source),
      path: window.location.pathname.slice(0, 500),
      line: Number.isInteger(payload?.line) && payload.line >= 0 ? payload.line : null,
      column: Number.isInteger(payload?.column) && payload.column >= 0 ? payload.column : null,
      stack: String(payload?.stack || '').slice(0, 6000),
      kind: String(payload?.kind || 'javascript').slice(0, 80),
    };

    fetch(ENDPOINT, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {
      // Diagnostics must never interfere with the application itself.
    });
  }

  window.addEventListener('error', (event) => {
    const error = event.error;
    report({
      kind: 'javascript',
      message: error?.message || event.message || 'Unhandled JavaScript error',
      source: event.filename,
      line: event.lineno,
      column: event.colno,
      stack: error?.stack || '',
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    report({
      kind: 'unhandled-rejection',
      message: reason?.message || String(reason || 'Unhandled promise rejection'),
      stack: reason?.stack || '',
    });
  });

  window.PlaylistMuseDiagnostics = Object.freeze({report});
})();
