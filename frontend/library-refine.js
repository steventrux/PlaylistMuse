(() => {
  'use strict';

  const ENDPOINT = '/api/library/playlists';
  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;

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

  function createTrackList(playlist, {addedKeys = new Set()} = {}) {
    const list = document.createElement('ol');
    list.className = 'library-refine-preview-list';
    (playlist?.tracks || []).forEach((track) => {
      const item = document.createElement('li');
      item.textContent = trackText(track);
      if (addedKeys.has(trackKey(track))) {
        item.classList.add('library-refine-track-added');
      }
      list.append(item);
    });
    return list;
  }

  function createChangeGroup(title, tracks, className) {
    const group = document.createElement('section');
    group.className = 'library-refine-change-group';

    const heading = document.createElement('h5');
    heading.textContent = title;

    const list = document.createElement('ul');
    list.className = 'library-refine-change-list';
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

  function updateCurrentSession(record) {
    let current = null;
    try {
      current = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
    } catch {
      current = null;
    }
    if (current?.library_id !== record.id) return;

    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      ...record.playlist,
      library_id: record.id,
    }));
    if (record.generation_request) {
      sessionStorage.setItem(REQUEST_KEY, JSON.stringify(record.generation_request));
    }
  }

  function install({item, actions, detailsInner, reload}) {
    if (!item || item.status !== 'draft' || !actions || !detailsInner) return;

    const refine = document.createElement('button');
    refine.type = 'button';
    refine.className = 'secondary library-refine-trigger';
    refine.textContent = 'Refine';
    refine.title = 'Fine-tune this draft with another prompt';

    const panel = document.createElement('section');
    panel.className = 'library-refine-panel hidden';
    panel.setAttribute('aria-label', `Refine ${item.name || 'playlist'}`);

    const label = document.createElement('label');
    label.className = 'library-refine-label';
    label.textContent = 'Fine-tune this draft';

    const textarea = document.createElement('textarea');
    textarea.rows = 3;
    textarea.maxLength = 1000;
    textarea.placeholder = 'e.g. More blues, less classic rock, and make the ending more energetic.';
    label.append(textarea);

    const hint = document.createElement('p');
    hint.className = 'library-refine-hint';
    hint.textContent = 'The current draft stays unchanged until you apply the preview.';

    const status = document.createElement('p');
    status.className = 'library-refine-status hidden';
    status.setAttribute('aria-live', 'polite');

    const trackArea = document.createElement('section');
    trackArea.className = 'library-refine-track-area';

    const trackHeading = document.createElement('h4');
    trackHeading.className = 'library-refine-track-heading';
    trackHeading.textContent = 'Current playlist';

    const trackBody = document.createElement('div');
    trackBody.className = 'library-refine-track-body';
    trackArea.append(trackHeading, trackBody);

    const controls = document.createElement('div');
    controls.className = 'library-refine-actions';

    const previewButton = document.createElement('button');
    previewButton.type = 'button';
    previewButton.className = 'primary';
    previewButton.textContent = 'Preview';
    previewButton.disabled = true;

    const applyButton = document.createElement('button');
    applyButton.type = 'button';
    applyButton.className = 'primary hidden';
    applyButton.textContent = 'Apply changes';

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'secondary';
    cancelButton.textContent = 'Cancel';

    controls.append(previewButton, applyButton, cancelButton);
    panel.append(label, hint, status, trackArea, controls);
    detailsInner.append(panel);
    actions.insertBefore(refine, actions.children[1] || null);

    let currentPlaylist = null;
    let previewPlaylist = null;
    let previewInstruction = '';
    let loadingCurrent = false;

    function setStatus(text = '', error = false) {
      status.textContent = text;
      status.classList.toggle('hidden', !text);
      status.classList.toggle('error', error);
    }

    function renderCurrentPlaylist() {
      trackHeading.textContent = 'Current playlist';
      trackBody.replaceChildren(createTrackList(currentPlaylist));
    }

    function renderComparison(proposed) {
      const currentTracks = Array.isArray(currentPlaylist?.tracks) ? currentPlaylist.tracks : [];
      const proposedTracks = Array.isArray(proposed?.tracks) ? proposed.tracks : [];
      const currentKeys = new Set(currentTracks.map(trackKey));
      const proposedKeys = new Set(proposedTracks.map(trackKey));
      const removed = currentTracks.filter((track) => !proposedKeys.has(trackKey(track)));
      const added = proposedTracks.filter((track) => !currentKeys.has(trackKey(track)));
      const addedKeys = new Set(added.map(trackKey));

      trackHeading.textContent = 'Refinement preview';
      const content = document.createDocumentFragment();

      if (removed.length || added.length) {
        const changes = document.createElement('div');
        changes.className = 'library-refine-change-grid';
        if (removed.length) {
          changes.append(createChangeGroup('Removed', removed, 'library-refine-track-removed'));
        }
        if (added.length) {
          changes.append(createChangeGroup('Added', added, 'library-refine-track-added'));
        }
        content.append(changes);
      } else {
        const unchanged = document.createElement('p');
        unchanged.className = 'library-refine-no-substitutions';
        unchanged.textContent = 'No track substitutions in this preview.';
        content.append(unchanged);
      }

      const proposedHeading = document.createElement('h5');
      proposedHeading.className = 'library-refine-proposed-heading';
      proposedHeading.textContent = 'Proposed playlist';
      content.append(proposedHeading, createTrackList(proposed, {addedKeys}));
      trackBody.replaceChildren(content);
    }

    async function loadCurrentPlaylist() {
      if (currentPlaylist || loadingCurrent) return;
      loadingCurrent = true;
      previewButton.disabled = true;
      trackHeading.textContent = 'Current playlist';
      const loading = document.createElement('p');
      loading.className = 'library-refine-loading';
      loading.textContent = 'Loading tracks…';
      trackBody.replaceChildren(loading);

      try {
        const record = await readJson(await fetch(
          `${ENDPOINT}/${encodeURIComponent(item.id)}`,
          {cache: 'no-store'},
        ));
        currentPlaylist = record.playlist;
        renderCurrentPlaylist();
        previewButton.disabled = false;
      } catch (error) {
        setStatus(error.message || String(error), true);
        trackBody.replaceChildren();
      } finally {
        loadingCurrent = false;
      }
    }

    function resetPreview() {
      previewPlaylist = null;
      previewInstruction = '';
      applyButton.classList.add('hidden');
      previewButton.classList.remove('hidden');
      if (currentPlaylist) renderCurrentPlaylist();
      setStatus('');
    }

    function closePanel() {
      panel.classList.add('hidden');
      refine.setAttribute('aria-expanded', 'false');
      textarea.value = '';
      resetPreview();
    }

    refine.setAttribute('aria-expanded', 'false');
    refine.addEventListener('click', (event) => {
      event.stopPropagation();
      const opening = panel.classList.contains('hidden');
      panel.classList.toggle('hidden', !opening);
      refine.setAttribute('aria-expanded', String(opening));
      if (opening) {
        textarea.focus();
        void loadCurrentPlaylist();
      } else {
        closePanel();
      }
    });

    panel.addEventListener('click', (event) => event.stopPropagation());
    panel.addEventListener('keydown', (event) => event.stopPropagation());
    textarea.addEventListener('input', resetPreview);

    cancelButton.addEventListener('click', closePanel);

    previewButton.addEventListener('click', async () => {
      const instruction = textarea.value.trim();
      if (instruction.length < 3) {
        setStatus('Add a short refinement instruction first.', true);
        textarea.focus();
        return;
      }
      if (!currentPlaylist) {
        setStatus('The current playlist is still loading.', true);
        return;
      }

      const reset = setLoadingButton(previewButton, {
        label: 'Refining',
        resetText: 'Preview',
      });
      textarea.disabled = true;
      cancelButton.disabled = true;
      setStatus('Building a refinement preview…');

      try {
        const payload = await readJson(await fetch(
          `${ENDPOINT}/${encodeURIComponent(item.id)}/refine-preview`,
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
        applyButton.classList.remove('hidden');
        setStatus(summaryText(payload.summary));
      } catch (error) {
        setStatus(error.message || String(error), true);
      } finally {
        textarea.disabled = false;
        cancelButton.disabled = false;
        reset();
      }
    });

    applyButton.addEventListener('click', async () => {
      if (!previewPlaylist || !previewInstruction) return;

      const reset = setLoadingButton(applyButton, {
        label: 'Applying',
        resetText: 'Apply changes',
      });
      textarea.disabled = true;
      previewButton.disabled = true;
      cancelButton.disabled = true;
      setStatus('Applying refinement…');

      try {
        const record = await readJson(await fetch(
          `${ENDPOINT}/${encodeURIComponent(item.id)}/refine-apply`,
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              instruction: previewInstruction,
              playlist: previewPlaylist,
            }),
          },
        ));
        updateCurrentSession(record);
        await reload();
      } catch (error) {
        setStatus(error.message || String(error), true);
        textarea.disabled = false;
        previewButton.disabled = false;
        cancelButton.disabled = false;
        reset();
      }
    });
  }

  window.PlaylistMuseLibraryRefine = {install};
})();
