(() => {
  'use strict';

  const DEBOUNCE_MS = 500;

  function analysisPayload(prompt, settings = {}) {
    return {
      prompt: String(prompt || '').trim(),
      track_count: Math.max(5, Math.min(100, Number.parseInt(settings.trackCount, 10) || 25)),
      options: {
        exclude_live: Boolean(settings.excludeLive),
        exclude_covers: Boolean(settings.excludeCovers),
        exclude_remixes: Boolean(settings.excludeRemixes),
      },
    };
  }

  function init() {
    const prompt = document.getElementById('prompt');
    const indicator = document.getElementById('prompt-complexity');
    if (!prompt || !indicator) return;

    const score = document.getElementById('prompt-complexity-score');
    const summary = document.getElementById('prompt-complexity-summary');
    const clarity = document.getElementById('prompt-clarity');
    const cache = new Map();
    let timer = null;
    let controller = null;
    let requestSequence = 0;

    const settings = () => ({
      trackCount: document.getElementById('track-count')?.value,
      excludeLive: document.getElementById('exclude-live')?.checked,
      excludeCovers: document.getElementById('exclude-covers')?.checked,
      excludeRemixes: document.getElementById('exclude-remixes')?.checked,
    });

    const render = (result) => {
      score.textContent = `${result.level} · ${result.score}/100`;
      const constraintCount = result.hard_constraints + result.soft_constraints;
      summary.textContent = [
        `${result.dimensions} musical ${result.dimensions === 1 ? 'dimension' : 'dimensions'}`,
        `${constraintCount} ${constraintCount === 1 ? 'constraint' : 'constraints'}`,
        `${result.structures} structural ${result.structures === 1 ? 'rule' : 'rules'}`,
      ].join(' · ');
      const issueSummary = result.issues.length ? ` · ${result.issues.join(' · ')}` : '';
      clarity.textContent = `Clarity: ${result.clarity_level}${issueSummary}`;
      indicator.classList.remove('hidden');
    };

    const analyze = async () => {
      const payload = analysisPayload(prompt.value, settings());
      if (!payload.prompt) {
        controller?.abort();
        indicator.classList.add('hidden');
        return;
      }

      const key = JSON.stringify(payload);
      if (cache.has(key)) {
        render(cache.get(key));
        return;
      }

      controller?.abort();
      controller = new AbortController();
      const sequence = ++requestSequence;
      try {
        const response = await fetch('/api/prompts/analyze', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: key,
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('Prompt analysis unavailable');
        const result = await response.json();
        if (sequence !== requestSequence) return;
        cache.set(key, result);
        render(result);
      } catch (error) {
        if (error.name !== 'AbortError' && sequence === requestSequence) {
          indicator.classList.add('hidden');
        }
      }
    };

    const schedule = () => {
      window.clearTimeout(timer);
      controller?.abort();
      timer = window.setTimeout(analyze, DEBOUNCE_MS);
    };

    prompt.addEventListener('input', schedule);
    ['track-count', 'exclude-live', 'exclude-covers', 'exclude-remixes'].forEach((id) => {
      document.getElementById(id)?.addEventListener('change', schedule);
    });
  }

  window.PlaylistMusePromptComplexity = {analysisPayload, debounceMs: DEBOUNCE_MS};
  if (typeof document !== 'undefined') init();
})();
