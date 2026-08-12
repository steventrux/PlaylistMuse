(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const ENDPOINT = '/api/library/playlists';
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;

  const trigger = $('refine-playlist');
  const host = $('playlist-refine-host');
  if (!trigger || !host) return;

  let currentRecord = null;
  let previewPlaylist = null;
  let previewInstruction = '';
  let previewScope = null;
  let scopeMode = 'all';

  function sessionPlaylist() {
    try {
      return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
    } catch {
      return null;
    }
  }

  function trackText(track) {
    const title = String(track?.title || 'Unknown track').trim();
    const artists = String(track?.artists || track?.artist || 'Unknown artist').trim();
    return `${title} — ${artists}`;
  }

  function normalized(value) {
    return String(value || '').trim().toLocaleLowerCase().replace(/\s+/g, ' ');
  }

  function trackKey(track) {
    const videoId = String(track?.video_id || '').trim();
    if (videoId) return `video:${videoId}`;
    return `text:${normalized(track?.title)}|${normalized(track?.artists || track?.artist)}`;
  }

  function createChangeGroup(title, tracks, className) {
    const group = document.createElement('section');
    group.className = 'playlist-refine-change-group';
    const heading = document.createElement('h5');
    heading.textContent = title;
    const list = document.createElement('ul');
    list.className = 'playlist-refine-change-list';
    tracks.forEach((track) => {
      const item = document.createElement('li');
      item.className = className;
      item.textContent = trackText(track);
      list.append(item);
    });
    group.append(heading, list);
    return group;
  }

  function summaryText(summary = {}) {
    const tracks = Number(summary.tracks || 0);
    const kept = Number(summary.kept || 0);
    const changed = Number(summary.changed || 0);
    const reordered = Number(summary.reordered || 0);
    const targeted = Number(summary.targeted || tracks);
    const locked = Number(summary.locked || 0);
    const parts = [`${kept}/${tracks} tracks kept`, `${changed} changed`];
    if (targeted < tracks) parts.push(`${targeted} targeted`);
    if (locked) parts.push(`${locked} locked`);
    if (reordered) parts.push(`${reordered} repositioned`);
    return `Preview ready · ${parts.join(' · ')}`;
  }

  function setStatus(text = '', error = false) {
    const status = host.querySelector('.playlist-refine-status');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('hidden', !text);
    status.classList.toggle('error', error);
  }

  function renderComparison(proposed) {
    const container = host.querySelector('.playlist-refine-changes');
    if (!container || !currentRecord) return;

    const currentTracks = Array.isArray(currentRecord.playlist?.tracks)
      ? currentRecord.playlist.tracks
      : [];
    const proposedTracks = Array.isArray(proposed?.tracks) ? proposed.tracks : [];
    const currentKeys = new Set(currentTracks.map(trackKey));
    const proposedKeys = new Set(proposedTracks.map(trackKey));
    const removed = currentTracks.filter((track) => !proposedKeys.has(trackKey(track)));
    const added = proposedTracks.filter((track) => !currentKeys.has(trackKey(track)));

    const content = document.createDocumentFragment();
    if (removed.length || added.length) {
      const changes = document.createElement('div');
      changes.className = 'playlist-refine-change-grid';
      if (removed.length) {
        changes.append(createChangeGroup('Removed', removed, 'playlist-refine-track-removed'));
      }
      if (added.length) {
        changes.append(createChangeGroup('Added', added, 'playlist-refine-track-added'));
      }
      content.append(changes);
    } else {
      const unchanged = document.createElement('p');
      unchanged.className = 'playlist-refine-no-substitutions';
      unchanged.textContent = 'No track substitutions in this preview.';
      content.append(unchanged);
    }

    container.replaceChildren(content);
    container.classList.remove('hidden');
  }

  function resetPreview() {
    previewPlaylist = null;
    previewInstruction = '';
    previewScope = null;
    host.querySelector('.playlist-refine-apply')?.classList.add('hidden');
    host.querySelector('.playlist-refine-preview')?.classList.remove('hidden');
    const changes = host.querySelector('.playlist-refine-changes');
    changes?.replaceChildren();
    changes?.classList.add('hidden');
    setStatus('');
  }

  function closePanel() {
    host.replaceChildren();
    currentRecord = null;
    previewPlaylist = null;
    previewInstruction = '';
    previewScope = null;
    scopeMode = 'all';
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus();
  }

  function studioRows() {
    return [...host.querySelectorAll('.playlist-studio-track')];
  }

  function setScopeMode(mode) {
    scopeMode = mode === 'selected' ? 'selected' : 'all';
    host.querySelectorAll('.playlist-studio-mode').forEach((button) => {
      const active = button.dataset.mode === scopeMode;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    const selectedTools = host.querySelector('.playlist-studio-selection-tools');
    selectedTools?.classList.toggle('hidden', scopeMode !== 'selected');
    studioRows().forEach((row) => {
      row.querySelector('.playlist-studio-target-wrap')?.classList.toggle(
        'hidden',
        scopeMode !== 'selected',
      );
    });
    resetPreview();
  }

  function selectedPositions(selector) {
    return studioRows()
      .filter((row) => row.querySelector(selector)?.checked)
      .map((row) => Number(row.dataset.position))
      .filter((position) => Number.isInteger(position) && position > 0);
  }

  function currentStudioScope() {
    const lockedPositions = selectedPositions('.playlist-studio-lock');
    let targetPositions = [];
    if (scopeMode === 'selected') {
      targetPositions = selectedPositions('.playlist-studio-target').filter(
        (position) => !lockedPositions.includes(position),
      );
      if (!targetPositions.length) {
        throw new Error('Select at least one unlocked track to refine.');
      }
    }
    return {
      target_positions: targetPositions,
      locked_positions: lockedPositions,
    };
  }

  function createToggleButton(label, mode) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary playlist-studio-mode';
    button.dataset.mode = mode;
    button.textContent = label;
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => setScopeMode(mode));
    return button;
  }

  function syncLockControl(lock, lockWrap, position) {
    const action = lock.checked ? 'Unlock' : 'Lock';
    lock.setAttribute('aria-label', `${action} track ${position}`);
    lockWrap.title = `${action} track ${position}`;
  }

  function createLockIcon() {
    const icon = document.createElement('span');
    icon.className = 'playlist-studio-lock-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = [
      '<svg class="playlist-studio-lock-open" viewBox="0 0 24 24" focusable="false">',
      '<rect x="5" y="10" width="14" height="10" rx="2"/>',
      '<path d="M9 10V7a4 4 0 0 1 7.2-2.4"/>',
      '</svg>',
      '<svg class="playlist-studio-lock-closed" viewBox="0 0 24 24" focusable="false">',
      '<rect x="5" y="10" width="14" height="10" rx="2"/>',
      '<path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
      '</svg>',
    ].join('');
    return icon;
  }

  function renderStudioScope() {
    const container = host.querySelector('.playlist-studio-scope');
    if (!container || !currentRecord) return;
    const tracks = Array.isArray(currentRecord.playlist?.tracks)
      ? currentRecord.playlist.tracks
      : [];

    const intro = document.createElement('div');
    intro.className = 'playlist-studio-scope-head';
    const title = document.createElement('strong');
    title.textContent = 'Editing scope';
    const copy = document.createElement('span');
    copy.textContent = 'Edit the whole draft or only selected tracks. Locked tracks stay unchanged.';
    intro.append(title, copy);

    const modes = document.createElement('div');
    modes.className = 'playlist-studio-modes';
    modes.setAttribute('role', 'group');
    modes.setAttribute('aria-label', 'Playlist Studio editing scope');
    modes.append(
      createToggleButton('All tracks', 'all'),
      createToggleButton('Selected tracks', 'selected'),
    );

    const selectionTools = document.createElement('div');
    selectionTools.className = 'playlist-studio-selection-tools hidden';
    const selectAll = document.createElement('button');
    selectAll.type = 'button';
    selectAll.className = 'playlist-studio-text-action';
    selectAll.textContent = 'Select all';
    selectAll.addEventListener('click', () => {
      studioRows().forEach((row) => {
        const target = row.querySelector('.playlist-studio-target');
        const lock = row.querySelector('.playlist-studio-lock');
        if (target && !lock?.checked) target.checked = true;
      });
      resetPreview();
    });
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'playlist-studio-text-action';
    clear.textContent = 'Clear selection';
    clear.addEventListener('click', () => {
      studioRows().forEach((row) => {
        const target = row.querySelector('.playlist-studio-target');
        if (target) target.checked = false;
      });
      resetPreview();
    });
    selectionTools.append(selectAll, clear);

    const list = document.createElement('div');
    list.className = 'playlist-studio-track-list';
    tracks.forEach((track, index) => {
      const position = index + 1;
      const row = document.createElement('div');
      row.className = 'playlist-studio-track';
      row.dataset.position = String(position);

      const targetWrap = document.createElement('label');
      targetWrap.className = 'playlist-studio-target-wrap hidden';
      const target = document.createElement('input');
      target.type = 'checkbox';
      target.className = 'playlist-studio-target';
      target.setAttribute('aria-label', `Edit track ${position}`);
      const targetLabel = document.createElement('span');
      targetLabel.textContent = 'Edit';
      targetWrap.append(target, targetLabel);

      const text = document.createElement('span');
      text.className = 'playlist-studio-track-text';
      const titleText = document.createElement('span');
      titleText.className = 'playlist-studio-track-title';
      titleText.textContent = `${position}. ${String(track?.title || 'Unknown track').trim()}`;
      const artistText = document.createElement('span');
      artistText.className = 'playlist-studio-track-artist';
      artistText.textContent = `— ${String(track?.artists || track?.artist || 'Unknown artist').trim()}`;

      const lockWrap = document.createElement('label');
      lockWrap.className = 'playlist-studio-lock-wrap';
      const lock = document.createElement('input');
      lock.type = 'checkbox';
      lock.className = 'playlist-studio-lock';
      lockWrap.append(lock, createLockIcon());
      syncLockControl(lock, lockWrap, position);

      target.addEventListener('change', () => {
        if (target.checked && lock.checked) {
          lock.checked = false;
          syncLockControl(lock, lockWrap, position);
        }
        resetPreview();
      });
      lock.addEventListener('change', () => {
        if (lock.checked) target.checked = false;
        syncLockControl(lock, lockWrap, position);
        resetPreview();
      });

      text.append(titleText, lockWrap, artistText);
      row.append(targetWrap, text);
      list.append(row);
    });

    container.replaceChildren(intro, modes, selectionTools, list);
    setScopeMode('all');
  }

  async function loadCurrentPlaylist() {
    const editor = window.PlaylistMusePlaylistEditor;
    if (!editor?.flushPersistence) throw new Error('The playlist editor is not ready yet.');
    const libraryId = await editor.flushPersistence();
    const record = await readJson(await fetch(
      `${ENDPOINT}/${encodeURIComponent(libraryId)}`,
      {cache: 'no-store'},
    ));
    if (record.status !== 'draft') throw new Error('Published playlists cannot be refined.');
    currentRecord = record;
    renderStudioScope();
  }

  async function buildPreview() {
    const textarea = host.querySelector('.playlist-refine-instruction');
    const previewButton = host.querySelector('.playlist-refine-preview');
    const cancelButton = host.querySelector('.playlist-refine-cancel');
    const instruction = textarea?.value.trim() || '';
    if (instruction.length < 3) {
      setStatus('Add a short refinement instruction first.', true);
      textarea?.focus();
      return;
    }
    if (!currentRecord) {
      setStatus('The current playlist is still loading.', true);
      return;
    }

    let scope;
    try {
      scope = currentStudioScope();
    } catch (error) {
      setStatus(error.message || String(error), true);
      return;
    }

    const reset = setLoadingButton(previewButton, {label: 'Refining', resetText: 'Preview'});
    textarea.disabled = true;
    cancelButton.disabled = true;
    setStatus('Building a Playlist Studio preview…');
    try {
      const payload = await readJson(await fetch(
        `${ENDPOINT}/${encodeURIComponent(currentRecord.id)}/studio-preview`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({instruction, ...scope}),
        },
      ));
      previewPlaylist = payload.playlist;
      previewInstruction = instruction;
      previewScope = scope;
      renderComparison(previewPlaylist);
      previewButton.classList.add('hidden');
      host.querySelector('.playlist-refine-apply')?.classList.remove('hidden');
      setStatus(summaryText(payload.summary));
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      textarea.disabled = false;
      cancelButton.disabled = false;
      reset();
    }
  }

  async function applyPreview() {
    if (!currentRecord || !previewPlaylist || !previewInstruction || !previewScope) return;
    const textarea = host.querySelector('.playlist-refine-instruction');
    const previewButton = host.querySelector('.playlist-refine-preview');
    const applyButton = host.querySelector('.playlist-refine-apply');
    const cancelButton = host.querySelector('.playlist-refine-cancel');
    const reset = setLoadingButton(applyButton, {label: 'Applying', resetText: 'Apply changes'});
    textarea.disabled = true;
    previewButton.disabled = true;
    cancelButton.disabled = true;
    setStatus('Applying Playlist Studio changes…');
    try {
      const record = await readJson(await fetch(
        `${ENDPOINT}/${encodeURIComponent(currentRecord.id)}/studio-apply`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            instruction: previewInstruction,
            playlist: previewPlaylist,
            ...previewScope,
          }),
        },
      ));
      const editor = window.PlaylistMusePlaylistEditor;
      if (!editor?.applyRecord) {
        throw new Error('The playlist editor could not apply the saved refinement.');
      }
      editor.applyRecord(record);
    } catch (error) {
      textarea.disabled = false;
      previewButton.disabled = false;
      cancelButton.disabled = false;
      reset();
      setStatus(error.message || String(error), true);
    }
  }

  async function openPanel() {
    if (host.firstElementChild) {
      closePanel();
      return;
    }
    if (sessionPlaylist()?.youtube_playlist?.url) return;

    const panel = document.createElement('section');
    panel.className = 'playlist-refine-panel';
    panel.setAttribute('aria-label', 'Playlist Studio');

    const head = document.createElement('div');
    head.className = 'playlist-editor-panel-head';
    const heading = document.createElement('strong');
    heading.textContent = 'Playlist Studio';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'secondary playlist-editor-close';
    close.textContent = 'Close';
    close.addEventListener('click', closePanel);
    head.append(heading, close);

    const label = document.createElement('label');
    label.className = 'playlist-refine-label';
    label.textContent = 'Fine-tune this draft';
    const textarea = document.createElement('textarea');
    textarea.className = 'playlist-refine-instruction';
    textarea.rows = 3;
    textarea.maxLength = 1000;
    textarea.placeholder = 'e.g. Make the selected tracks progressively more energetic without changing the locked songs.';
    textarea.addEventListener('input', resetPreview);
    label.append(textarea);

    const hint = document.createElement('p');
    hint.className = 'playlist-refine-hint';
    hint.textContent = 'Target only the tracks you want the AI to edit. Locked tracks remain exactly unchanged.';

    const scope = document.createElement('section');
    scope.className = 'playlist-studio-scope';
    scope.setAttribute('aria-label', 'Playlist Studio track scope');
    const loadingScope = document.createElement('p');
    loadingScope.className = 'playlist-refine-hint';
    loadingScope.textContent = 'Loading track scope…';
    scope.append(loadingScope);

    const status = document.createElement('p');
    status.className = 'playlist-refine-status hidden';
    status.setAttribute('aria-live', 'polite');

    const changes = document.createElement('section');
    changes.className = 'playlist-refine-changes hidden';
    changes.setAttribute('aria-label', 'Refinement changes');

    const actions = document.createElement('div');
    actions.className = 'playlist-refine-actions';
    const previewButton = document.createElement('button');
    previewButton.type = 'button';
    previewButton.className = 'primary playlist-refine-preview';
    previewButton.textContent = 'Preview';
    previewButton.disabled = true;
    previewButton.addEventListener('click', () => void buildPreview());
    const applyButton = document.createElement('button');
    applyButton.type = 'button';
    applyButton.className = 'primary playlist-refine-apply hidden';
    applyButton.textContent = 'Apply changes';
    applyButton.addEventListener('click', () => void applyPreview());
    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'secondary playlist-refine-cancel';
    cancelButton.textContent = 'Cancel';
    cancelButton.addEventListener('click', closePanel);
    actions.append(previewButton, applyButton, cancelButton);

    panel.append(head, label, hint, scope, status, changes, actions);
    host.append(panel);
    trigger.setAttribute('aria-expanded', 'true');
    textarea.focus();

    try {
      await loadCurrentPlaylist();
      previewButton.disabled = false;
    } catch (error) {
      setStatus(error.message || String(error), true);
    }
  }

  trigger.setAttribute('aria-expanded', 'false');
  trigger.addEventListener('click', () => void openPanel());
  window.addEventListener('playlistmuse-playlist-published', closePanel);
})();