(() => {
  'use strict';

  const PLAYLIST_ACTION_SELECTOR = [
    '#add-track',
    '#refine-playlist',
    'a.primary.track-action',
    '.replace-track-button',
    '.remove-track-button',
    '.track-move-button',
  ].join(', ');
  const LIBRARY_OPEN_SELECTOR = '.library-actions > a.primary';

  const ICONS = Object.freeze({
    youtube: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="3.5" y="5.5" width="17" height="13" rx="4"/><path d="m10 9 5 3-5 3Z"/></svg>',
    replace: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 7h-9a4 4 0 0 0-4 4v1"/><path d="m17 4 3 3-3 3"/><path d="M4 17h9a4 4 0 0 0 4-4v-1"/><path d="m7 20-3-3 3-3"/></svg>',
    remove: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="m6.5 7 1 13h9l1-13"/><path d="M10 11v5M14 11v5"/></svg>',
    up: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 19V5"/><path d="m6.5 10.5 5.5-5.5 5.5 5.5"/></svg>',
    down: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14"/><path d="m6.5 13.5 5.5 5.5 5.5-5.5"/></svg>',
    add: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"/></svg>',
    refine: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>',
  });

  const ACTIONS = Object.freeze({
    youtube: {label: 'Open in YouTube Music', icon: ICONS.youtube},
    replace: {label: 'Replace track', icon: ICONS.replace},
    remove: {label: 'Remove track', icon: ICONS.remove},
    up: {label: 'Move up', icon: ICONS.up},
    down: {label: 'Move down', icon: ICONS.down},
    add: {label: 'Add track', icon: ICONS.add},
    refine: {label: 'Playlist Studio', icon: ICONS.refine},
  });

  function elementsWithin(root, selector) {
    const elements = [];
    if (root instanceof Element && root.matches(selector)) elements.push(root);
    root.querySelectorAll?.(selector).forEach((element) => elements.push(element));
    return elements;
  }

  function decorateCompactAction(element, actionName) {
    const action = ACTIONS[actionName];
    if (!element || !action || element.classList.contains('is-loading')) return;
    if (
      element.dataset.compactAction === actionName
      && element.querySelector('.compact-action-icon')
      && element.querySelector('.compact-action-label')
    ) {
      return;
    }

    const icon = document.createElement('span');
    icon.className = 'compact-action-icon';
    icon.innerHTML = action.icon;

    const label = document.createElement('span');
    label.className = 'compact-action-label';
    label.textContent = action.label;

    element.replaceChildren(icon, label);
    element.classList.add('compact-action');
    element.dataset.compactAction = actionName;
    element.setAttribute('aria-label', action.label);
    element.title = action.label;
  }

  function compactActionName(element) {
    if (element.id === 'add-track') return 'add';
    if (element.id === 'refine-playlist') return 'refine';
    if (element.classList.contains('replace-track-button')) return 'replace';
    if (element.classList.contains('remove-track-button')) return 'remove';
    if (element.classList.contains('track-move-button')) {
      return element.textContent.trim().toLocaleLowerCase().includes('down') ? 'down' : 'up';
    }
    if (element.matches('a.primary.track-action')) return 'youtube';
    return '';
  }

  function decoratePlaylistActions(root = document) {
    elementsWithin(root, PLAYLIST_ACTION_SELECTOR).forEach((element) => {
      const actionName = element.dataset.compactAction || compactActionName(element);
      if (actionName) decorateCompactAction(element, actionName);
    });
  }

  function normalizeLibraryOpenActions(root = document) {
    elementsWithin(root, LIBRARY_OPEN_SELECTOR).forEach((link) => {
      const text = link.textContent.trim();
      if (text === 'Edit') link.textContent = 'Open';
      if (text === 'Editing…') link.textContent = 'Opening…';

      const ariaLabel = link.getAttribute('aria-label') || '';
      if (ariaLabel.startsWith('Edit ')) {
        link.setAttribute('aria-label', `Open ${ariaLabel.slice(5)}`);
      }
    });
  }

  function refresh(root = document) {
    decoratePlaylistActions(root);
    normalizeLibraryOpenActions(root);
  }

  refresh();

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.target instanceof Element) refresh(mutation.target);
    });
  });

  observer.observe(document.body, {childList: true, subtree: true});
})();
