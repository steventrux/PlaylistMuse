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
