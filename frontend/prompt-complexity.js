(() => {
  'use strict';

  const DEBOUNCE_MS = 500;
  const FILTER_CONFLICT_PREFIX = 'FILTER_CONFLICT::';
  let latestFilterConflicts = [];
  let ensureCurrentAnalysisImpl = async () => null;

  function complexityHue(value) {
    const score = Math.max(0, Math.min(100, Number(value) || 0));
    return Math.round(120 - (score * 1.2));
  }

  function displayLevel(level) {
    return level === 'Detailed' ? 'Simple' : level;
  }

  function parseFilterConflict(issue) {
    const text = String(issue || '');
    if (!text.startsWith(FILTER_CONFLICT_PREFIX)) return null;
    const remainder = text.slice(FILTER_CONFLICT_PREFIX.length);
    const separator = remainder.indexOf('::');
    if (separator < 0) return null;
    const option = remainder.slice(0, separator).trim();
    const message = remainder.slice(separator + 2).trim();
    if (!option || !message) return null;
    return {option, message};
  }

  function filterConflicts(result) {
    const issues = Array.isArray(result?.issues) ? result.issues : [];
    return issues.map(parseFilterConflict).filter(Boolean);
  }

  function visibleIssues(result) {
    const issues = Array.isArray(result?.issues) ? result.issues : [];
    return issues.map((issue) => {
      const conflict = parseFilterConflict(issue);
      return conflict ? conflict.message : String(issue || '').trim();
    }).filter(Boolean);
  }

  function clarityText(result) {
    const level = String(result.clarity_level || '');
    if (['excellent', 'good'].includes(level.toLowerCase())) return `Clarity: ${level}`;
    const issues = visibleIssues(result);
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

  function conflictWarningNode() {
    let node = document.getElementById('prompt-filter-conflict-warning');
    if (node) return node;
    node = document.createElement('div');
    node.id = 'prompt-filter-conflict-warning';
    node.className = 'generation-feedback generation-feedback-incomplete hidden';
    node.setAttribute('role', 'alert');
    node.setAttribute('aria-live', 'polite');
    node.dataset.feedbackIcon = '⚠';
    const controls = document.getElementById('generation-controls');
    const aiWarning = document.getElementById('ai-generation-warning');
    if (controls && aiWarning) controls.insertBefore(node, aiWarning);
    else controls?.append(node);
    return node;
  }

  function renderFilterConflicts(conflicts) {
    latestFilterConflicts = Array.isArray(conflicts) ? conflicts : [];
    const node = conflictWarningNode();
    if (!latestFilterConflicts.length) {
      node.textContent = '';
      node.classList.add('hidden');
      return;
    }
    node.textContent = latestFilterConflicts.map((item) => item.message).join(' ');
    node.classList.remove('hidden');
  }

  function activeFilterConflicts() {
    return latestFilterConflicts.map((item) => ({...item}));
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
      component.classList.add('hidden');
      setPopoverOpen(false);
      renderFilterConflicts([]);
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
      renderFilterConflicts(filterConflicts(result));
      component.classList.remove('hidden');
    };

    const analyze = async () => {
      const payload = analysisPayload(prompt.value, settings());
      if (!payload.prompt) {
        controller?.abort();
        hideComponent();
        return null;
      }

      const key = JSON.stringify(payload);
      if (cache.has(key)) {
        const cached = cache.get(key);
        render(cached);
        return cached;
      }

      controller?.abort();
      const requestController = new AbortController();
      controller = requestController;
      const sequence = ++requestSequence;
      try {
        const response = await fetch('/api/prompts/analyze', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: key,
          signal: requestController.signal,
        });
        if (!response.ok) throw new Error('Prompt analysis unavailable');
        const result = await response.json();
        if (sequence !== requestSequence) return null;
        cache.set(key, result);
        render(result);
        return result;
      } catch (error) {
        if (error.name !== 'AbortError' && sequence === requestSequence) hideComponent();
        return null;
      } finally {
        if (controller === requestController) controller = null;
      }
    };

    ensureCurrentAnalysisImpl = async () => {
      window.clearTimeout(timer);
      timer = null;
      return analyze();
    };

    const schedule = () => {
      window.clearTimeout(timer);
      controller?.abort();
      timer = window.setTimeout(() => {
        timer = null;
        void analyze();
      }, DEBOUNCE_MS);
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
    activeFilterConflicts,
    analysisPayload,
    clarityText,
    complexityHue,
    displayLevel,
    ensureCurrentAnalysis: () => ensureCurrentAnalysisImpl(),
    filterConflicts,
    parseFilterConflict,
    debounceMs: DEBOUNCE_MS,
  };
  if (typeof document !== 'undefined') init();
})();
