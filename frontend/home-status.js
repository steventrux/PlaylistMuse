(() => {
  'use strict';

  const HEADER_BANNER_URL = '/static/playlistmuse-banner.svg?v=1';
  const FAVICON_URL = '/static/playlistmuse-favicon.png?v=1';
  const REPOSITORY_URL = 'https://github.com/steventrux/PlaylistMuse';

  function ensureBrandStyles() {
    if (document.querySelector('link[href^="/static/brand.css"]')) return;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = '/static/brand.css?v=2';
    document.head.append(stylesheet);
  }

  function ensureFavicon() {
    let favicon = document.querySelector('link[rel~="icon"]');
    if (!favicon) {
      favicon = document.createElement('link');
      favicon.rel = 'icon';
      document.head.append(favicon);
    }
    favicon.type = 'image/png';
    favicon.href = FAVICON_URL;
  }

  function installBrandBanner() {
    const header = document.querySelector('.app-header');
    if (!header || header.querySelector('.brand-banner')) return;

    const copy = header.firstElementChild;
    if (!copy) return;

    const lockup = document.createElement('div');
    lockup.className = 'brand-lockup';

    const banner = document.createElement('img');
    banner.className = 'brand-banner';
    banner.src = HEADER_BANNER_URL;
    banner.alt = '';
    banner.setAttribute('aria-hidden', 'true');

    copy.classList.add('brand-copy', 'brand-copy-accessible');
    header.insertBefore(lockup, copy);
    lockup.append(banner);
  }

  const $ = (id) => document.getElementById(id);
  const INDICATOR_STATES = ['pending', 'on', 'off', 'error'];
  const providerLabels = {
    gemini: 'Gemini',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    openrouter_auto: 'OpenRouter Auto',
    openrouter_free: 'OpenRouter Free',
    ollama: 'Ollama',
    custom: 'Custom',
  };

  // Friendly names for known OpenAI-compatible hosts, so a custom endpoint
  // pointing at a recognizable provider isn't just labeled by its hostname.
  const knownCustomHosts = {
    'api.x.ai': 'Grok',
    'api.groq.com': 'Groq',
    'api.together.xyz': 'Together AI',
    'api.together.ai': 'Together AI',
    'api.deepseek.com': 'DeepSeek',
    'api.mistral.ai': 'Mistral',
    'api.fireworks.ai': 'Fireworks AI',
    'api.perplexity.ai': 'Perplexity',
    'api.cerebras.ai': 'Cerebras',
  };

  let closeNavigation = () => {};

  const brainIcon = `
    <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <path class="brain-outline" d="M13.2 6.1a4.2 4.2 0 0 0-7.3 3 4.7 4.7 0 0 0-2.6 7.7 4.4 4.4 0 0 0 3.4 7.1 4.2 4.2 0 0 0 6.5 2.1" />
      <path class="brain-outline" d="M18.8 6.1a4.2 4.2 0 0 1 7.3 3 4.7 4.7 0 0 1 2.6 7.7 4.4 4.4 0 0 1-3.4 7.1 4.2 4.2 0 0 1-6.5 2.1" />
      <path class="brain-outline" d="M13.2 6.1c1.3.7 2 1.9 2 3.5v3.1M18.8 6.1c-1.3.7-2 1.9-2 3.5v3.1M9.1 11.1c1.7.2 2.8 1.1 3.2 2.7M22.9 11.1c-1.7.2-2.8 1.1-3.2 2.7M8 20.7c1.9-.5 3.4 0 4.5 1.5M24 20.7c-1.9-.5-3.4 0-4.5 1.5" />
      <path class="brain-bolt" d="m17.2 10-5 7.8h4.1l-1.4 5.4 5.1-7.7h-4.2l1.4-5.5Z" />
    </svg>
  `;

  const providerIcons = {
    gemini: `
      <svg class="provider-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path class="provider-fill" d="M16 3.5c1.15 7.25 4.25 10.35 11.5 11.5C20.25 16.15 17.15 19.25 16 26.5 14.85 19.25 11.75 16.15 4.5 15 11.75 13.85 14.85 10.75 16 3.5Z" />
      </svg>
    `,
    openai: `
      <svg class="provider-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path class="provider-stroke" d="M12.2 7.1A5.1 5.1 0 0 1 21 8.5a5.1 5.1 0 0 1 4.6 7.6 5.1 5.1 0 0 1-4.3 7.8 5.1 5.1 0 0 1-8.8.1 5.1 5.1 0 0 1-4.6-7.6 5.1 5.1 0 0 1 4.3-7.8Z" />
        <path class="provider-stroke" d="m11.5 11 4.5-2.6 4.5 2.6v5.2L16 18.8l-4.5-2.6V11Zm0 5.2v5.2m9-10.4 4.5 2.6M16 18.8V24" />
      </svg>
    `,
    anthropic: `
      <svg class="provider-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path class="provider-fill" fill-rule="evenodd" d="M5.8 25 13.7 6h4.6l7.9 19h-4.7l-1.8-4.7h-7.5L10.4 25H5.8Zm8-8.6h4.4L16 10.6l-2.2 5.8Z" />
      </svg>
    `,
    openrouter_auto: `
      <svg class="provider-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path class="provider-stroke" d="M5 9h8.2c3.2 0 3.8 7 7.2 7H27M5 23h8.2c3.2 0 3.8-7 7.2-7" />
        <circle class="provider-fill" cx="5" cy="9" r="2.2" /><circle class="provider-fill" cx="5" cy="23" r="2.2" /><circle class="provider-fill" cx="27" cy="16" r="2.2" />
      </svg>
    `,
    openrouter_free: `
      <svg class="provider-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path class="provider-stroke" d="M5 9h8.2c3.2 0 3.8 7 7.2 7H27M5 23h8.2c3.2 0 3.8-7 7.2-7" />
        <circle class="provider-fill" cx="5" cy="9" r="2.2" /><circle class="provider-fill" cx="5" cy="23" r="2.2" /><circle class="provider-fill" cx="27" cy="16" r="2.2" />
      </svg>
    `,
    ollama: `
      <svg class="provider-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path class="provider-stroke" d="M10 12.5V8.8c0-2.1 1.4-3.8 3.2-3.8 1.2 0 2.2.7 2.8 1.8.6-1.1 1.6-1.8 2.8-1.8C20.6 5 22 6.7 22 8.8v3.7c2.2 1.6 3.5 4.1 3.5 7 0 4.8-4 7.5-9.5 7.5s-9.5-2.7-9.5-7.5c0-2.9 1.3-5.4 3.5-7Z" />
        <circle class="provider-fill" cx="12.5" cy="18" r="1.2" /><circle class="provider-fill" cx="19.5" cy="18" r="1.2" /><path class="provider-stroke" d="M13 22c1.9 1.1 4.1 1.1 6 0" />
      </svg>
    `,
    custom: `
      <svg class="provider-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path class="provider-stroke" d="m12 8-7 8 7 8m8-16 7 8-7 8M18 6l-4 20" />
      </svg>
    `,
  };

  const youtubeIcon = `
    <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect class="youtube-body" x="3.5" y="8" width="25" height="16" rx="5.5" />
      <path class="youtube-play" d="m13.4 12.4 7.2 3.6-7.2 3.6v-7.2Z" />
    </svg>
  `;

  const lastFmIcon = `
    <svg class="lastfm-mark" viewBox="0 0 512 512" aria-hidden="true" focusable="false">
      <path d="M225.8 367.1l-18.8-51s-30.5 34-76.2 34c-40.5 0-69.2-35.2-69.2-91.5 0-72.1 36.4-97.9 72.1-97.9 66.5 0 74.8 53.3 100.9 134.9 18.8 56.9 54 102.6 155.4 102.6 72.7 0 122-22.3 122-80.9 0-72.9-62.7-80.6-115-92.1-25.8-5.9-33.4-16.4-33.4-34 0-19.9 15.8-31.7 41.6-31.7 28.2 0 43.4 10.6 45.7 35.8l58.6-7c-4.7-52.8-41.1-74.5-100.9-74.5-52.8 0-104.4 19.9-104.4 83.9 0 39.9 19.4 65.1 68 76.8 44.9 10.6 79.8 13.8 79.8 45.7 0 21.7-21.1 30.5-61 30.5-59.2 0-83.9-31.1-97.9-73.9-32-96.8-43.6-163-161.3-163C45.7 113.8 0 168.3 0 261c0 89.1 45.7 137.2 127.9 137.2 66.2 0 97.9-31.1 97.9-31.1z" />
    </svg>
  `;

  const githubIcon = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path fill="currentColor" d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2.24c-3.22.7-3.9-1.37-3.9-1.37-.52-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.2 1.77 1.2 1.04 1.77 2.72 1.26 3.38.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.29-5.27-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.47.11-3.05 0 0 .97-.31 3.16 1.18a10.93 10.93 0 0 1 5.76 0c2.2-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.09 0 4.41-2.71 5.4-5.29 5.69.42.36.79 1.07.79 2.16v3.2c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z" />
    </svg>
  `;

  function ensureStylesheet(prefix, href) {
    const existing = document.querySelector(`link[href^="${prefix}"]`);
    if (existing) {
      if (existing.getAttribute('href') !== href) existing.setAttribute('href', href);
      return existing;
    }
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.append(link);
    return link;
  }

  function ensureStatusStyles() {
    ensureStylesheet('/static/layout.css', '/static/layout.css?v=7');
    ensureStylesheet('/static/header-navigation.css', '/static/header-navigation.css?v=21');
    ensureStylesheet('/static/settings-dialog.css', '/static/settings-dialog.css?v=11');
  }

  function currentPage() {
    const path = window.location.pathname;
    if (path.endsWith('/library.html')) return 'library';
    if (path.endsWith('/favorites.html')) return 'favorites';
    if (path.endsWith('/statistics.html')) return 'statistics';
    if (path === '/' || path.endsWith('/index.html') || path.endsWith('/playlist.html')) return 'create';
    return '';
  }

  async function refreshBuildInfo(sidebar) {
    const version = sidebar?.querySelector('#sidebar-build-version');
    const repository = sidebar?.querySelector('.sidebar-repo-link');
    if (!version || !repository) return;

    try {
      const response = await fetch('/api/version', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const info = await response.json();
      version.textContent = info.display || info.version || 'Version unavailable';
      if (info.repository_url) repository.href = info.repository_url;
    } catch {
      version.textContent = 'Version unavailable';
    }
  }

  async function refreshUpdateStatus(sidebar) {
    const version = sidebar?.querySelector('#sidebar-build-version');
    const badge = sidebar?.querySelector('#sidebar-update-badge');
    if (!version || !badge) return;

    try {
      const response = await fetch('/api/version/update', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const info = await response.json();
      const available = Boolean(info.update_available);
      if (available && info.url) badge.href = info.url;
      version.classList.toggle('sidebar-build-version--update', available);
      badge.hidden = !available;
    } catch {
      version.classList.remove('sidebar-build-version--update');
      badge.hidden = true;
    }
  }

  function createNavigationShell() {
    const existing = document.querySelector('.playlistmuse-sidebar');
    if (existing) return existing;

    const header = document.querySelector('.app-header');
    if (!header) return null;

    const toggle = document.createElement('button');
    toggle.id = 'sidebar-menu-toggle';
    toggle.className = 'sidebar-menu-toggle';
    toggle.type = 'button';
    toggle.setAttribute('aria-controls', 'playlistmuse-sidebar');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open navigation menu');
    toggle.title = 'Menu';
    toggle.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M5 7h14M5 12h14M5 17h14" />
      </svg>
    `;
    header.append(toggle);

    const backdrop = document.createElement('div');
    backdrop.className = 'sidebar-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');

    const sidebar = document.createElement('aside');
    sidebar.id = 'playlistmuse-sidebar';
    sidebar.className = 'playlistmuse-sidebar';
    sidebar.setAttribute('aria-label', 'PlaylistMuse navigation');
    sidebar.setAttribute('aria-hidden', 'true');
    sidebar.innerHTML = `
      <div class="sidebar-head">
        <img class="sidebar-brand-banner" src="${HEADER_BANNER_URL}" alt="PlaylistMuse">
        <button class="sidebar-close" type="button" aria-label="Close navigation menu">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </div>
      <nav class="sidebar-nav" aria-label="Main navigation">
        <section class="sidebar-group" aria-labelledby="sidebar-integrations-label">
          <p id="sidebar-integrations-label" class="sidebar-group-label">Integrations</p>
          <div class="header-actions header-service-status" aria-label="Service configuration status"></div>
        </section>
        <section class="sidebar-group" aria-labelledby="sidebar-library-label">
          <p id="sidebar-library-label" class="sidebar-group-label">Library</p>
          <a class="sidebar-link" data-page="favorites" href="/static/favorites.html">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M12 20.5s-7.5-4.6-10-9.1C.5 8 2 5 5.2 5c1.9 0 3.4 1 4.8 2.8C11.4 6 12.9 5 14.8 5 18 5 19.5 8 19.5 11.4c-2.5 4.5-7.5 9.1-7.5 9.1Z" />
            </svg>
            <span>Favorites</span>
          </a>
          <a class="sidebar-link" data-page="statistics" href="/static/statistics.html">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M5 19h14" />
              <path d="M8 19v-6M13 19V9M18 19v-9" />
            </svg>
            <span>Statistics</span>
          </a>
        </section>
      </nav>
      <div class="sidebar-footer">
        <span class="sidebar-version-row">
          <span id="sidebar-build-version" class="sidebar-build-version">Checking version…</span>
          <a id="sidebar-update-badge" class="sidebar-update-badge" href="${REPOSITORY_URL}" target="_blank" rel="noopener noreferrer" title="New version available" aria-label="New version available" hidden>
            <svg class="sidebar-update-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </a>
        </span>
        <a class="sidebar-repo-link" href="${REPOSITORY_URL}" target="_blank" rel="noopener noreferrer" aria-label="PlaylistMuse repository on GitHub">
          ${githubIcon}
          <span>GitHub</span>
        </a>
      </div>
    `;

    document.body.append(backdrop, sidebar);
    void refreshBuildInfo(sidebar);
    void refreshUpdateStatus(sidebar);

    const activePage = currentPage();
    sidebar.querySelectorAll('.sidebar-link').forEach((link) => {
      const active = link.dataset.page === activePage;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
    });

    const closeButton = sidebar.querySelector('.sidebar-close');
    const open = () => {
      document.body.classList.add('sidebar-open');
      sidebar.setAttribute('aria-hidden', 'false');
      toggle.setAttribute('aria-expanded', 'true');
      toggle.setAttribute('aria-label', 'Close navigation menu');
      closeButton?.focus();
    };
    const close = ({restoreFocus = true} = {}) => {
      document.body.classList.remove('sidebar-open');
      sidebar.setAttribute('aria-hidden', 'true');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open navigation menu');
      if (restoreFocus) toggle.focus();
    };
    closeNavigation = close;

    toggle.addEventListener('click', () => {
      if (document.body.classList.contains('sidebar-open')) close();
      else open();
    });
    closeButton?.addEventListener('click', () => close());
    backdrop.addEventListener('click', () => close());
    sidebar.querySelectorAll('.sidebar-link').forEach((link) => {
      link.addEventListener('click', () => close({restoreFocus: false}));
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
        close();
      }
    });

    return sidebar;
  }

  function createHeaderStatus() {
    ensureStatusStyles();
    const sidebar = createNavigationShell();
    if (!sidebar) return null;

    const controls = sidebar.querySelector('.header-service-status');
    if (!controls) return null;

    if (!$('header-ai-status')) {
      const ai = document.createElement('button');
      ai.id = 'header-ai-status';
      ai.className = 'header-indicator ai pending';
      ai.type = 'button';
      ai.dataset.tooltip = 'Checking AI provider configuration';
      ai.setAttribute('aria-label', 'Checking AI provider configuration');
      ai.innerHTML = brainIcon;
      controls.append(ai);
    }

    if (!$('header-youtube-status')) {
      const youtube = document.createElement('button');
      youtube.id = 'header-youtube-status';
      youtube.className = 'header-indicator youtube pending';
      youtube.type = 'button';
      youtube.dataset.tooltip = 'Checking YouTube Music configuration';
      youtube.setAttribute('aria-label', 'Checking YouTube Music configuration');
      youtube.innerHTML = youtubeIcon;
      controls.append(youtube);
    }

    if (!$('header-lastfm-status')) {
      const lastfm = document.createElement('button');
      lastfm.id = 'header-lastfm-status';
      lastfm.className = 'header-indicator lastfm pending';
      lastfm.type = 'button';
      lastfm.dataset.tooltip = 'Checking Last.fm configuration';
      lastfm.setAttribute('aria-label', 'Checking Last.fm configuration');
      lastfm.innerHTML = lastFmIcon;
      controls.append(lastfm);
    }

    return controls;
  }

  function setIndicatorState(element, state, tooltip) {
    if (!element) return;
    element.classList.remove(...INDICATOR_STATES);
    element.classList.add(state);
    element.dataset.tooltip = tooltip;
    element.setAttribute('aria-label', tooltip);
  }

  function setAiProviderIcon(element, provider, label) {
    if (!element) return;
    element.innerHTML = providerIcons[provider] || brainIcon;
    element.dataset.provider = provider || '';
    element.dataset.providerLabel = label || '';
  }

  function resolveProviderLabel(provider, profile) {
    if (provider === 'custom') {
      let host = '';
      try {
        host = new URL(profile.base_url || '').hostname;
      } catch {
        host = '';
      }
      if (!host) return providerLabels.custom;
      return knownCustomHosts[host] || `Custom · ${host}`;
    }
    return providerLabels[provider] || provider;
  }

  function setGenerationAvailability(state) {
    const button = $('generate');
    const warning = $('ai-generation-warning');
    if (!button || !warning) return;

    const warningTitle = $('ai-generation-warning-title');
    const warningText = $('ai-generation-warning-text');
    const configured = state === 'configured';

    button.disabled = !configured;
    button.setAttribute('aria-disabled', String(!configured));
    button.classList.toggle('hidden', !configured);
    warning.classList.toggle('hidden', configured || state === 'pending');

    if (state === 'unconfigured') {
      warningTitle.textContent = 'AI provider not configured';
      warningText.textContent = 'Configure an AI provider before generating a playlist.';
    } else if (state === 'error') {
      warningTitle.textContent = 'AI configuration could not be verified';
      warningText.textContent = 'Open AI Settings and check the provider configuration before generating.';
    }
  }

  async function refreshAiStatus(indicator) {
    try {
      const response = await fetch('/api/ai/profiles', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const provider = data.active_provider || '';
      const profile = data.profiles?.[provider] || {};
      const configured = Boolean(provider && profile.configured);

      setAiProviderIcon(indicator, configured ? provider : '', configured ? resolveProviderLabel(provider, profile) : '');
      setIndicatorState(
        indicator,
        configured ? 'on' : 'off',
        configured
          ? `AI active · ${resolveProviderLabel(provider, profile)} · ${profile.model}`
          : 'AI not configured · click to open AI Settings',
      );
      setGenerationAvailability(configured ? 'configured' : 'unconfigured');
    } catch {
      setAiProviderIcon(indicator, '');
      setIndicatorState(indicator, 'error', 'Unable to check AI configuration · click to open AI Settings');
      setGenerationAvailability('error');
    }
  }

  async function refreshYouTubeStatus(indicator) {
    try {
      const response = await fetch('/api/youtube/status');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();
      const connected = Boolean(status.account_connected);
      let tooltip;

      if (connected) {
        tooltip = status.account_name
          ? `YouTube Music configured · ${status.account_name}`
          : 'YouTube Music configured and connected';
      } else if (status.credentials_configured) {
        tooltip = 'YouTube Music credentials saved · click to connect the account';
      } else {
        tooltip = 'YouTube Music not configured · click to open YouTube Settings';
      }

      setIndicatorState(indicator, connected ? 'on' : 'off', tooltip);
    } catch {
      setIndicatorState(
        indicator,
        'error',
        'Unable to check YouTube Music configuration · click to open YouTube Settings',
      );
    }
  }

  async function refreshLastFmStatus(indicator) {
    try {
      const response = await fetch('/api/lastfm/status', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const status = await response.json();
      const configured = Boolean(status.configured);
      setIndicatorState(
        indicator,
        configured ? 'on' : 'off',
        configured
          ? 'Last.fm configured · recommendations active'
          : 'Last.fm not configured · click to add an API key',
      );
      window.dispatchEvent(new CustomEvent('playlistmuse-lastfm-status', {
        detail: {configured},
      }));
    } catch {
      setIndicatorState(
        indicator,
        'error',
        'Unable to check Last.fm configuration · click to open Last.fm Settings',
      );
      window.dispatchEvent(new CustomEvent('playlistmuse-lastfm-status', {
        detail: {configured: false},
      }));
    }
  }

  function openSettings(section) {
    window.PlaylistMuseCommon.openSettings(section);
  }

  function bindIndicatorActions() {
    $('header-ai-status')?.addEventListener('click', () => {
      closeNavigation({restoreFocus: false});
      openSettings('ai');
    });
    $('header-youtube-status')?.addEventListener('click', () => {
      closeNavigation({restoreFocus: false});
      openSettings('youtube');
    });
    $('header-lastfm-status')?.addEventListener('click', () => {
      closeNavigation({restoreFocus: false});
      openSettings('lastfm');
    });
  }

  async function refreshStatus() {
    createHeaderStatus();
    const aiIndicator = $('header-ai-status');
    const youtubeIndicator = $('header-youtube-status');
    const lastFmIndicator = $('header-lastfm-status');

    setAiProviderIcon(aiIndicator, '');
    setIndicatorState(aiIndicator, 'pending', 'Checking AI provider configuration');
    setIndicatorState(youtubeIndicator, 'pending', 'Checking YouTube Music configuration');
    setIndicatorState(lastFmIndicator, 'pending', 'Checking Last.fm configuration');
    setGenerationAvailability('pending');

    const checks = [
      refreshAiStatus(aiIndicator),
      refreshYouTubeStatus(youtubeIndicator),
    ];

    /* On the home page the dedicated Last.fm module owns its status refresh
     * and availability event. Other pages use the same endpoint here so the
     * sidebar remains complete and consistent everywhere. */
    if (!$('setup-dialog')) checks.push(refreshLastFmStatus(lastFmIndicator));

    await Promise.all(checks);
  }

  ensureBrandStyles();
  ensureFavicon();
  installBrandBanner();
  createHeaderStatus();
  bindIndicatorActions();
  window.addEventListener('playlistmuse-status-changed', refreshStatus);
  void refreshStatus();
})();
