(function (root, factory) {
  'use strict';

  const api = factory();

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PlaylistMuseCommon = api;
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  'use strict';

  async function readJson(response, options = {}) {
    const text = await response.text();
    let payload = {};

    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(text || `HTTP ${response.status}`);
    }

    if (!response.ok) {
      const detail = payload.detail ?? payload.error ?? payload.message;
      if (options.flattenValidationErrors && Array.isArray(detail)) {
        const message = detail
          .map((item) => item?.msg || item?.message || String(item))
          .join('; ');
        throw new Error(message);
      }
      throw new Error(
        typeof detail === 'string'
          ? detail
          : JSON.stringify(detail || payload),
      );
    }

    return payload;
  }

  function setLoadingButton(button, options) {
    const {
      label,
      resetText,
      ariaLabel = '',
      onStart = null,
      onReset = null,
    } = options;

    const spinner = document.createElement('span');
    spinner.className = 'generation-spinner';
    spinner.setAttribute('aria-hidden', 'true');

    const labelElement = document.createElement('span');
    labelElement.className = 'generation-label';
    labelElement.textContent = label;

    const dots = document.createElement('span');
    dots.className = 'generation-dots';
    dots.setAttribute('aria-hidden', 'true');
    dots.append(
      document.createElement('span'),
      document.createElement('span'),
      document.createElement('span'),
    );

    button.replaceChildren(spinner, labelElement, dots);
    button.classList.add('is-loading');
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    if (ariaLabel) button.setAttribute('aria-label', ariaLabel);
    if (typeof onStart === 'function') onStart();

    let active = true;
    return () => {
      if (!active) return;
      active = false;
      button.classList.remove('is-loading');
      button.removeAttribute('aria-busy');
      if (ariaLabel) button.removeAttribute('aria-label');
      button.disabled = false;
      button.textContent = resetText;
      if (typeof onReset === 'function') onReset();
    };
  }

  return Object.freeze({readJson, setLoadingButton});
}));

(() => {
  'use strict';

  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src^="${src}"]`);
      if (existing) {
        resolve();
        return;
      }
      const script = document.createElement('script');
      script.src = `${src}?v=1`;
      script.onload = resolve;
      script.onerror = reject;
      document.body.append(script);
    });
  }

  async function loadLastFmEnhancements() {
    if (!document.querySelector('link[href^="/static/lastfm.css"]')) {
      const stylesheet = document.createElement('link');
      stylesheet.rel = 'stylesheet';
      stylesheet.href = '/static/lastfm.css?v=1';
      document.head.append(stylesheet);
    }

    try {
      if (document.getElementById('setup-dialog')) {
        await loadScript('/static/lastfm-settings.js');
      }
      await loadScript('/static/lastfm-status.js');
    } catch {
      // Last.fm is optional and must never block the existing interface.
    }
  }

  function primaryNavigationTarget() {
    const path = window.location.pathname;
    if (path.endsWith('/library.html')) {
      return document.querySelector('.library-card');
    }
    if (path === '/' || path.endsWith('/index.html')) {
      return document.querySelector('.hero.card');
    }
    return null;
  }

  function ensurePrimaryNavigationStyles() {
    if (document.querySelector('link[href^="/static/primary-navigation.css"]')) return;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = '/static/primary-navigation.css?v=1';
    document.head.append(stylesheet);
  }

  function installPrimaryNavigationTabs() {
    const target = primaryNavigationTarget();
    if (!target || target.querySelector('.primary-page-tabs')) return;

    const pageGroup = document.querySelector(
      '.playlistmuse-sidebar .sidebar-group[aria-labelledby="sidebar-pages-label"]',
    );
    if (!pageGroup) return;

    const links = Array.from(pageGroup.querySelectorAll('.sidebar-link'));
    if (!links.length) return;

    ensurePrimaryNavigationStyles();

    const tabs = document.createElement('nav');
    tabs.className = 'primary-page-tabs';
    tabs.setAttribute('aria-label', 'Primary playlist navigation');

    links.forEach((link) => {
      const label = link.querySelector('span')?.textContent?.trim()
        || link.textContent.trim();
      const active = link.getAttribute('aria-current') === 'page';

      link.className = 'primary-page-tab';
      link.classList.toggle('active', active);
      link.replaceChildren(label);
      tabs.append(link);
    });

    const sidebar = pageGroup.closest('.playlistmuse-sidebar');
    const sidebarNav = pageGroup.closest('.sidebar-nav');
    pageGroup.remove();
    if (sidebar) sidebar.setAttribute('aria-label', 'PlaylistMuse integrations');
    if (sidebarNav) sidebarNav.setAttribute('aria-label', 'Integrations');

    target.prepend(tabs);
  }

  function installPromptAssessmentStyles() {
    if (document.getElementById('prompt-assessment-styles')) return;
    const style = document.createElement('style');
    style.id = 'prompt-assessment-styles';
    style.textContent = `
      .prompt-assessment {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: .65rem;
        align-items: start;
        margin-top: .65rem;
        padding: .75rem .85rem;
        border: 1px solid transparent;
        border-radius: .75rem;
        font-size: .9rem;
        line-height: 1.45;
      }
      .prompt-assessment.hidden { display: none; }
      .prompt-assessment-icon {
        font-size: 1.05rem;
        line-height: 1.35;
      }
      .prompt-assessment-reasons {
        display: grid;
        gap: .2rem;
      }
      .prompt-assessment-impossible {
        color: #fecaca;
        background: rgba(127, 29, 29, .34);
        border-color: rgba(248, 113, 113, .58);
      }
      .prompt-assessment-ambiguous {
        color: #fde68a;
        background: rgba(113, 63, 18, .34);
        border-color: rgba(250, 204, 21, .52);
      }
    `;
    document.head.append(style);
  }

  function ensurePromptAssessment() {
    const prompt = document.getElementById('prompt');
    if (!prompt) return null;
    let assessment = document.getElementById('prompt-assessment');
    if (assessment) return assessment;

    assessment = document.createElement('div');
    assessment.id = 'prompt-assessment';
    assessment.className = 'prompt-assessment hidden';
    assessment.setAttribute('role', 'alert');
    assessment.setAttribute('aria-live', 'assertive');

    const icon = document.createElement('span');
    icon.className = 'prompt-assessment-icon';
    icon.setAttribute('aria-hidden', 'true');

    const reasons = document.createElement('div');
    reasons.className = 'prompt-assessment-reasons';

    assessment.append(icon, reasons);
    prompt.insertAdjacentElement('afterend', assessment);
    return assessment;
  }

  function clearPromptAssessment() {
    const assessment = document.getElementById('prompt-assessment');
    if (!assessment) return;
    assessment.className = 'prompt-assessment hidden';
    assessment.querySelector('.prompt-assessment-icon').textContent = '';
    assessment.querySelector('.prompt-assessment-reasons').replaceChildren();
  }

  function renderPromptAssessment(status, reasons = []) {
    const assessment = ensurePromptAssessment();
    if (!assessment || status === 'valid') {
      clearPromptAssessment();
      return;
    }

    const impossible = status === 'impossible';
    assessment.className = `prompt-assessment prompt-assessment-${status}`;
    assessment.querySelector('.prompt-assessment-icon').textContent = impossible ? '⛔' : '⚠️';

    const reasonsContainer = assessment.querySelector('.prompt-assessment-reasons');
    reasonsContainer.replaceChildren();
    const values = Array.isArray(reasons) && reasons.length
      ? reasons
      : [impossible
        ? 'The request contains mutually incompatible constraints.'
        : 'The request can be interpreted in more than one way.'];
    values.forEach((reason) => {
      const line = document.createElement('span');
      line.textContent = String(reason);
      reasonsContainer.append(line);
    });
  }

  function installPromptPreflight() {
    const prompt = document.getElementById('prompt');
    const generate = document.getElementById('generate');
    const promptPanel = document.getElementById('prompt-panel');
    if (!prompt || !generate || !promptPanel) return;

    installPromptAssessmentStyles();
    ensurePromptAssessment();

    prompt.addEventListener('input', () => {
      delete generate.dataset.validatedPrompt;
      clearPromptAssessment();
    });

    generate.addEventListener('click', async (event) => {
      if (promptPanel.classList.contains('hidden')) return;
      const normalized = prompt.value.trim().replace(/\s+/g, ' ');
      if (!normalized || generate.dataset.validatedPrompt === normalized) {
        delete generate.dataset.validatedPrompt;
        return;
      }

      event.preventDefault();
      event.stopImmediatePropagation();
      if (generate.dataset.assessing === 'true') return;

      const previousText = generate.textContent;
      generate.dataset.assessing = 'true';
      generate.disabled = true;
      generate.textContent = 'Checking request…';

      try {
        const response = await fetch('/api/playlists/validate-prompt', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({prompt: normalized}),
        });
        const result = await window.PlaylistMuseCommon.readJson(response, {
          flattenValidationErrors: true,
        });
        renderPromptAssessment(result.status, result.reasons);
        if (result.status === 'impossible') return;

        generate.dataset.validatedPrompt = normalized;
        generate.disabled = false;
        generate.textContent = previousText;
        generate.click();
      } catch {
        // Provider or validation failures must not make an otherwise valid request unusable.
        clearPromptAssessment();
        generate.dataset.validatedPrompt = normalized;
        generate.disabled = false;
        generate.textContent = previousText;
        generate.click();
      } finally {
        delete generate.dataset.assessing;
        if (generate.textContent === 'Checking request…') {
          generate.disabled = false;
          generate.textContent = previousText;
        }
      }
    }, true);
  }

  function initializeEnhancements() {
    installPrimaryNavigationTabs();
    installPromptPreflight();
    void loadLastFmEnhancements();
  }

  if (document.readyState === 'complete') {
    initializeEnhancements();
  } else {
    window.addEventListener('load', initializeEnhancements, {once: true});
  }
})();
