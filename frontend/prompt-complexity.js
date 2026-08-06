(() => {
  'use strict';

  const DEBOUNCE_MS = 500;

  function complexityHue(value) {
    const score = Math.max(0, Math.min(100, Number(value) || 0));
    return Math.round(120 - (score * 1.2));
  }

  function displayLevel(level) {
    return level === 'Detailed' ? 'Simple' : level;
  }

  function clarityText(result) {
    const level = String(result.clarity_level || '');
    if (['excellent', 'good'].includes(level.toLowerCase())) return `Clarity: ${level}`;
    const issues = Array.isArray(result.issues) ? result.issues : [];
    const issueSummary = issues.length ? ` · ${issues.join(' · ')}` : '';
    return `Clarity: ${level}${issueSummary}`;
  }

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
    const component = document.getElementById('prompt-complexity');
    const trigger = document.getElementById('prompt-complexity-trigger');
    const popover = document.getElementById('prompt-complexity-popover');
    const score = document.getElementById('prompt-complexity-score');
    const summary = document.getElementById('prompt-complexity-summary');
    const clarity = document.getElementById('prompt-clarity');
    if (!prompt || !component || !trigger || !popover || !score || !summary || !clarity) return;

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

    const setPopoverOpen = (open) => {
      trigger.setAttribute('aria-expanded', String(open));
      trigger.setAttribute('aria-label', open ? 'Hide request complexity' : 'Show request complexity');
      popover.hidden = !open;
    };

    const hideComponent = () => {
      controller?.abort();
      component.classList.add('hidden');
      setPopoverOpen(false);
    };

    const render = (result) => {
      const numericScore = Math.max(0, Math.min(100, Number(result.score) || 0));
      const level = displayLevel(result.level);
      component.style.setProperty('--complexity-hue', complexityHue(numericScore));
      component.style.setProperty('--complexity-score', `${numericScore}%`);
      score.textContent = `${level} · ${numericScore}/100`;
      trigger.title = `Request complexity: ${level} · ${numericScore}/100`;
      const constraintCount = result.hard_constraints + result.soft_constraints;
      summary.textContent = [
        `${result.dimensions} musical ${result.dimensions === 1 ? 'dimension' : 'dimensions'}`,
        `${constraintCount} ${constraintCount === 1 ? 'constraint' : 'constraints'}`,
        `${result.structures} structural ${result.structures === 1 ? 'rule' : 'rules'}`,
      ].join(' · ');
      clarity.textContent = clarityText(result);
      component.classList.remove('hidden');
    };

    const analyze = async () => {
      const payload = analysisPayload(prompt.value, settings());
      if (!payload.prompt) {
        hideComponent();
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
        if (error.name !== 'AbortError' && sequence === requestSequence) hideComponent();
      }
    };

    const schedule = () => {
      window.clearTimeout(timer);
      controller?.abort();
      timer = window.setTimeout(analyze, DEBOUNCE_MS);
    };

    trigger.addEventListener('click', () => {
      setPopoverOpen(trigger.getAttribute('aria-expanded') !== 'true');
    });
    document.addEventListener('click', (event) => {
      if (!component.contains(event.target)) setPopoverOpen(false);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') setPopoverOpen(false);
    });
    prompt.addEventListener('input', schedule);
    ['track-count', 'exclude-live', 'exclude-covers', 'exclude-remixes'].forEach((id) => {
      document.getElementById(id)?.addEventListener('change', schedule);
    });
  }

  window.PlaylistMusePromptComplexity = {
    analysisPayload,
    clarityText,
    complexityHue,
    displayLevel,
    debounceMs: DEBOUNCE_MS,
  };
  if (typeof document !== 'undefined') init();
})();
