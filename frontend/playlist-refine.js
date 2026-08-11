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
    const parts = [`${kept}/${tracks} tracks kept`, `${changed} changed`];
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
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus();
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

    const reset = setLoadingButton(previewButton, {label: 'Refining', resetText: 'Preview'});
    textarea.disabled = true;
    cancelButton.disabled = true;
    setStatus('Building a refinement preview…');
    try {
      const payload = await readJson(await fetch(
        `${ENDPOINT}/${encodeURIComponent(currentRecord.id)}/refine-preview`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({instruction}),
        },
      ));
      previewPlaylist = payload.playlist;
      previewInstruction = instruction;
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
    if (!currentRecord || !previewPlaylist || !previewInstruction) return;
    const textarea = host.querySelector('.playlist-refine-instruction');
    const previewButton = host.querySelector('.playlist-refine-preview');
    const applyButton = host.querySelector('.playlist-refine-apply');
    const cancelButton = host.querySelector('.playlist-refine-cancel');
    const reset = setLoadingButton(applyButton, {label: 'Applying', resetText: 'Apply changes'});
    textarea.disabled = true;
    previewButton.disabled = true;
    cancelButton.disabled = true;
    setStatus('Applying refinement…');
    try {
      const record = await readJson(await fetch(
        `${ENDPOINT}/${encodeURIComponent(currentRecord.id)}/refine-apply`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({instruction: previewInstruction, playlist: previewPlaylist}),
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
    panel.setAttribute('aria-label', 'Refine playlist');

    const head = document.createElement('div');
    head.className = 'playlist-editor-panel-head';
    const heading = document.createElement('strong');
    heading.textContent = 'Refine playlist';
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
    textarea.placeholder = 'e.g. More blues, less classic rock, and make the ending more energetic.';
    textarea.addEventListener('input', resetPreview);
    label.append(textarea);

    const hint = document.createElement('p');
    hint.className = 'playlist-refine-hint';
    hint.textContent = 'The current draft stays unchanged until you apply the preview.';

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

    panel.append(head, label, hint, status, changes, actions);
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
