(() => {
  'use strict';

  const ENDPOINT = '/api/library/playlists';
  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;

  function trackLabel(track, index) {
    const title = String(track?.title || 'Unknown track').trim();
    const artists = String(track?.artists || track?.artist || 'Unknown artist').trim();
    return `${index + 1}. ${title} — ${artists}`;
  }

  function createPreviewList(playlist) {
    const list = document.createElement('ol');
    list.className = 'library-refine-preview-list';
    (playlist?.tracks || []).forEach((track, index) => {
      const item = document.createElement('li');
      item.textContent = trackLabel(track, index).replace(/^\d+\.\s*/, '');
      list.append(item);
    });
    return list;
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

    const preview = document.createElement('div');
    preview.className = 'library-refine-preview hidden';

    const controls = document.createElement('div');
    controls.className = 'library-refine-actions';

    const previewButton = document.createElement('button');
    previewButton.type = 'button';
    previewButton.className = 'primary';
    previewButton.textContent = 'Preview';

    const applyButton = document.createElement('button');
    applyButton.type = 'button';
    applyButton.className = 'primary hidden';
    applyButton.textContent = 'Apply changes';

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'secondary';
    cancelButton.textContent = 'Cancel';

    controls.append(previewButton, applyButton, cancelButton);
    panel.append(label, hint, status, preview, controls);
    detailsInner.append(panel);
    actions.insertBefore(refine, actions.children[1] || null);

    let previewPlaylist = null;
    let previewInstruction = '';

    function setStatus(text = '', error = false) {
      status.textContent = text;
      status.classList.toggle('hidden', !text);
      status.classList.toggle('error', error);
    }

    function resetPreview() {
      previewPlaylist = null;
      previewInstruction = '';
      preview.replaceChildren();
      preview.classList.add('hidden');
      applyButton.classList.add('hidden');
      previewButton.classList.remove('hidden');
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
      if (opening) textarea.focus();
      else closePanel();
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
        preview.replaceChildren(createPreviewList(previewPlaylist));
        preview.classList.remove('hidden');
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
