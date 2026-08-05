(() => {
  'use strict';

  /*
   * home-status-core.js retains the existing service-status responsibilities:
   * - creates header-ai-status and header-youtube-status;
   * - calls setGenerationAvailability(configured ? 'configured' : 'unconfigured').
   */

  const currentScript = document.currentScript;
  const LOGO_URL = '/static/playlistmuse-logo.png?v=1';

  function ensureBrandStyles() {
    if (document.querySelector('link[href^="/static/brand.css"]')) return;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = '/static/brand.css?v=1';
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
    favicon.href = LOGO_URL;
  }

  function installBrandLogo() {
    const header = document.querySelector('.app-header');
    if (!header || header.querySelector('.brand-logo')) return;

    const copy = header.firstElementChild;
    if (!copy) return;

    const lockup = document.createElement('div');
    lockup.className = 'brand-lockup';

    const logo = document.createElement('img');
    logo.className = 'brand-logo';
    logo.src = LOGO_URL;
    logo.alt = '';
    logo.setAttribute('aria-hidden', 'true');

    copy.classList.add('brand-copy');
    header.insertBefore(lockup, copy);
    lockup.append(logo, copy);
  }

  function loadStatusCore() {
    const core = document.createElement('script');
    core.src = '/static/home-status-core.js?v=13';
    core.async = false;
    if (currentScript?.hasAttribute('data-playlistmuse-footer-status')) {
      core.setAttribute('data-playlistmuse-footer-status', '');
    }

    if (currentScript?.parentNode) {
      currentScript.parentNode.insertBefore(core, currentScript.nextSibling);
    } else {
      document.body.append(core);
    }
  }

  ensureBrandStyles();
  ensureFavicon();
  installBrandLogo();
  loadStatusCore();
})();
