(() => {
  'use strict';

  const PLAYLIST_ACTION_SELECTOR = [
    '#add-track',
    '#refine-playlist',
    '#playlist-feedback',
    '#export-playlist',
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
    feedback: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 5.5h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-8l-5 3v-3H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z"/><path d="M8 10h8M8 13h5"/></svg>',
    export: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 4v11"/><path d="m7.5 11 4.5 4.5 4.5-4.5"/><path d="M4.5 18.5v1a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-1"/></svg>',
    favorite: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35Z"/></svg>',
    favorited: '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="currentColor" stroke="none"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35Z"/></svg>',
  });

  // The classic Material Design "favorite" heart: every x-coordinate pairs up
  // with another that sums to 24, so it is exactly mirror-symmetric about the
  // vertical center of the 24x24 viewBox. That matters here because the split
  // icon below relies on a true bilateral symmetry, not just a heart-ish blob.
  const HEART_PATH = 'M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35Z';

  // A single-color (white) heart split down the middle so a "track or artist"
  // toggle can show, at a glance, whether the track, the artist, or both are
  // favorited: the left half fills for the artist, the right half for the track.
  //
  // This is ONE path painted with a hard-stop gradient (not two clipped copies
  // of the shape stacked on top of each other) so there is a single edge to
  // anti-alias: two independently clipped/stacked shapes leave a visible seam
  // where their edges meet, and clipping against the icon's square bounding
  // box (rather than the heart's own, off-center silhouette) makes the split
  // look lopsided. The gradient defaults to objectBoundingBox units, so its
  // 50% stop lines up with the actual midpoint of the heart shape.
  let splitFavoriteIconSeq = 0;
  function buildSplitFavoriteIconMarkup() {
    const gradientId = `favorite-split-fill-${++splitFavoriteIconSeq}`;
    return `<svg class="favorite-icon-split" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="${gradientId}" x1="0" y1="0" x2="1" y2="0">
          <stop class="favorite-icon-stop favorite-icon-stop--left" offset="0" stop-color="currentColor"/>
          <stop class="favorite-icon-stop favorite-icon-stop--left" offset="0.5" stop-color="currentColor"/>
          <stop class="favorite-icon-stop favorite-icon-stop--right" offset="0.5" stop-color="currentColor"/>
          <stop class="favorite-icon-stop favorite-icon-stop--right" offset="1" stop-color="currentColor"/>
        </linearGradient>
      </defs>
      <path d="${HEART_PATH}" fill="url(#${gradientId})" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
  }

  function describeFavoriteSplitState(trackFavorited, artistFavorited) {
    if (trackFavorited && artistFavorited) return 'Track and artist favorited';
    if (trackFavorited) return 'Track favorited';
    if (artistFavorited) return 'Artist favorited';
    return 'Not favorited';
  }

  const ACTIONS = Object.freeze({
    youtube: {label: 'Open in YouTube Music', icon: ICONS.youtube},
    replace: {label: 'Replace track', icon: ICONS.replace},
    remove: {label: 'Remove track', icon: ICONS.remove},
    up: {label: 'Move up', icon: ICONS.up},
    down: {label: 'Move down', icon: ICONS.down},
    add: {label: 'Add track', icon: ICONS.add},
    refine: {label: 'Playlist Studio', icon: ICONS.refine},
    feedback: {label: 'Give feedback', icon: ICONS.feedback},
    export: {label: 'Export', icon: ICONS.export},
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

  function decorateFavoriteToggle(element, {favorited, trackFavorited, artistFavorited, label = 'favorite'} = {}) {
    if (!element) return;
    const isSplit = trackFavorited !== undefined || artistFavorited !== undefined;
    const track = Boolean(trackFavorited);
    const artist = Boolean(artistFavorited);
    const anyFavorited = isSplit ? (track || artist) : Boolean(favorited);

    const icon = document.createElement('span');
    icon.className = 'compact-action-icon';
    if (isSplit) {
      icon.innerHTML = buildSplitFavoriteIconMarkup();
      const split = icon.querySelector('.favorite-icon-split');
      split.classList.toggle('is-track-favorited', track);
      split.classList.toggle('is-artist-favorited', artist);
    } else {
      icon.innerHTML = anyFavorited ? ICONS.favorited : ICONS.favorite;
    }

    const description = isSplit
      ? describeFavoriteSplitState(track, artist)
      : (anyFavorited ? `Remove ${label} from favorites` : `Add ${label} to favorites`);

    const text = document.createElement('span');
    text.className = 'compact-action-label';
    text.textContent = isSplit ? description : (anyFavorited ? 'Favorited' : 'Favorite');

    element.replaceChildren(icon, text);
    element.classList.add('compact-action', 'favorite-toggle-button');
    element.classList.toggle('is-favorited', anyFavorited);
    element.setAttribute('aria-pressed', String(anyFavorited));
    element.setAttribute('aria-label', description);
    element.title = description;
  }

  function compactActionName(element) {
    if (element.id === 'add-track') return 'add';
    if (element.id === 'refine-playlist') return 'refine';
    if (element.id === 'playlist-feedback') return 'feedback';
    if (element.id === 'export-playlist') return 'export';
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

  window.PlaylistMuseActionControls = {decorateFavoriteToggle};
})();
