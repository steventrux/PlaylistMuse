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

  const SETTINGS_SECTIONS = new Set(['ai', 'youtube', 'lastfm']);

  function openSettings(section) {
    const target = SETTINGS_SECTIONS.has(section) ? section : 'ai';
    if (
      window.location.pathname.endsWith('/settings.html')
      && typeof window.PlaylistMuseSettingsSelect === 'function'
    ) {
      window.PlaylistMuseSettingsSelect(target);
      return;
    }
    const url = new URL('/static/settings.html', window.location.origin);
    url.searchParams.set('section', target);
    window.location.assign(`${url.pathname}${url.search}`);
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

  return Object.freeze({readJson, setLoadingButton, openSettings});
}));

(() => {
  'use strict';

  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  function ensureLastFmStyles() {
    if (document.querySelector('link[href^="/static/lastfm.css"]')) return;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = '/static/lastfm.css?v=2';
    document.head.append(stylesheet);
  }

  function primaryNavigationHost() {
    const path = window.location.pathname;
    if (
      path.endsWith('/library.html')
      || path.endsWith('/playlist.html')
      || path.endsWith('/statistics.html')
      || path.endsWith('/statistics-detail.html')
      || path.endsWith('/diagnostics.html')
      || path.endsWith('/settings.html')
      || path.endsWith('/favorites.html')
      || path === '/'
      || path.endsWith('/index.html')
    ) {
      return document.querySelector('.app-header');
    }
    return null;
  }

  function ensurePrimaryNavigationStyles() {
    if (document.querySelector('link[href^="/static/primary-navigation.css"]')) return;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = '/static/primary-navigation.css?v=2';
    document.head.append(stylesheet);
  }

  const PRIMARY_PAGES = [
    {
      page: 'create',
      href: '/',
      label: 'Create playlist',
      icon: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9 18V6l10-2v12" /><circle cx="6.5" cy="18" r="2.5" /><circle cx="16.5" cy="16" r="2.5" /></svg>',
    },
    {
      page: 'library',
      href: '/static/library.html',
      label: 'My playlists',
      icon: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="5" cy="7" r="1" fill="currentColor" stroke="none" /><path d="M9 7h10" /><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><path d="M9 12h10" /><circle cx="5" cy="17" r="1" fill="currentColor" stroke="none" /><path d="M9 17h10" /></svg>',
    },
  ];

  function primaryPage() {
    const path = window.location.pathname;
    if (path.endsWith('/library.html')) return 'library';
    if (path === '/' || path.endsWith('/index.html') || path.endsWith('/playlist.html')) return 'create';
    return '';
  }

  function installPrimaryNavigation() {
    const host = primaryNavigationHost();
    if (!host || host.querySelector('.primary-page-navigation')) return;

    ensurePrimaryNavigationStyles();

    const navigation = document.createElement('nav');
    navigation.className = 'primary-page-navigation';
    navigation.setAttribute('aria-label', 'Primary playlist navigation');

    const active = primaryPage();
    PRIMARY_PAGES.forEach((entry) => {
      const link = document.createElement('a');
      link.className = 'primary-page-link';
      link.href = entry.href;
      link.dataset.page = entry.page;
      if (entry.page === active) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }
      link.innerHTML = entry.icon;
      const labelSpan = document.createElement('span');
      labelSpan.textContent = entry.label;
      link.append(labelSpan);
      navigation.append(link);
    });

    host.classList.add('has-primary-page-navigation');
    host.append(navigation);
  }

  function installSupportNavigation() {
    const sidebarNav = document.querySelector('.playlistmuse-sidebar .sidebar-nav');
    if (!sidebarNav || sidebarNav.querySelector('[data-page="diagnostics"]')) return;

    const group = document.createElement('section');
    group.className = 'sidebar-group';
    group.setAttribute('aria-labelledby', 'sidebar-support-label');
    group.innerHTML = `
      <p id="sidebar-support-label" class="sidebar-group-label">Support</p>
      <a class="sidebar-link" data-page="diagnostics" href="/static/diagnostics.html">
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="8.5" />
          <path d="M7.5 12h2.4l1.5-3.5 2.2 7 1.5-3.5h1.4" />
        </svg>
        <span>Diagnostics</span>
      </a>
    `;

    const activeLink = group.querySelector('[data-page="diagnostics"]');
    if (window.location.pathname.endsWith('/diagnostics.html')) {
      activeLink?.classList.add('active');
      activeLink?.setAttribute('aria-current', 'page');
    }

    // Support stays the last group in the sidebar, right above the footer, so
    // it's inserted after Library rather than appended blindly (in case a
    // future group gets added after Library too).
    const libraryGroup = sidebarNav.querySelector('[aria-labelledby="sidebar-library-label"]');
    if (libraryGroup) libraryGroup.after(group);
    else sidebarNav.append(group);
  }

  const THEME_STORAGE_KEY = 'playlistmuse-theme';
  const THEME_OPTIONS = [
    {value: 'system', label: 'System'},
    {value: 'light', label: 'Light'},
    {value: 'dark', label: 'Dark'},
  ];

  function ensureThemeToggleStyles() {
    if (document.querySelector('link[href^="/static/theme-toggle.css"]')) return;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = '/static/theme-toggle.css?v=2';
    document.head.append(stylesheet);
  }

  function storedTheme() {
    try {
      const value = window.localStorage.getItem(THEME_STORAGE_KEY);
      return value === 'light' || value === 'dark' ? value : 'system';
    } catch {
      return 'system';
    }
  }

  // The inline anti-flash script in <head> already stamps data-theme for a
  // stored light/dark choice before first paint; this keeps it in sync after
  // a toggle click and also drives the mobile browser-chrome theme-color.
  function applyTheme(value) {
    if (value === 'light' || value === 'dark') {
      document.documentElement.setAttribute('data-theme', value);
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    const isLight = value === 'light'
      || (value === 'system' && window.matchMedia('(prefers-color-scheme: light)').matches);
    meta.setAttribute('content', isLight ? '#f6f6fb' : '#070916');
  }

  function installThemeToggle() {
    const sidebarNav = document.querySelector('.playlistmuse-sidebar .sidebar-nav');
    if (!sidebarNav || sidebarNav.querySelector('[data-theme-option]')) return;

    ensureThemeToggleStyles();

    const current = storedTheme();
    applyTheme(current);

    const group = document.createElement('section');
    group.className = 'sidebar-group';
    group.setAttribute('aria-labelledby', 'sidebar-appearance-label');
    group.innerHTML = `
      <p id="sidebar-appearance-label" class="sidebar-group-label">Appearance</p>
      <div class="theme-toggle" role="radiogroup" aria-labelledby="sidebar-appearance-label">
        ${THEME_OPTIONS.map((option) => `
          <button
            type="button"
            class="theme-toggle-option${option.value === current ? ' active' : ''}"
            data-theme-option="${option.value}"
            role="radio"
            aria-checked="${option.value === current}"
          >${option.label}</button>
        `).join('')}
      </div>
    `;

    group.querySelectorAll('[data-theme-option]').forEach((button) => {
      button.addEventListener('click', () => {
        const value = button.dataset.themeOption;
        try {
          if (value === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
          else window.localStorage.setItem(THEME_STORAGE_KEY, value);
        } catch {
          // Storage unavailable (private browsing, disabled cookies) -- the
          // theme still applies for this page load, it just won't persist.
        }
        applyTheme(value);
        group.querySelectorAll('[data-theme-option]').forEach((other) => {
          const isActive = other === button;
          other.classList.toggle('active', isActive);
          other.setAttribute('aria-checked', String(isActive));
        });
      });
    });

    // Keep Appearance as the last group, right above the footer.
    const supportGroup = sidebarNav.querySelector('[aria-labelledby="sidebar-support-label"]');
    const libraryGroup = sidebarNav.querySelector('[aria-labelledby="sidebar-library-label"]');
    if (supportGroup) supportGroup.after(group);
    else if (libraryGroup) libraryGroup.after(group);
    else sidebarNav.append(group);
  }

  function initializeEnhancements() {
    installPrimaryNavigation();
    installSupportNavigation();
    installThemeToggle();
    ensureLastFmStyles();
  }

  if (document.readyState === 'complete') {
    initializeEnhancements();
  } else {
    window.addEventListener('load', initializeEnhancements, {once: true});
  }
})();
