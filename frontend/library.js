(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const ENDPOINT = '/api/library/playlists';
  const $ = (id) => document.getElementById(id);
  const {readJson, setLoadingButton} = window.PlaylistMuseCommon;

  function setStatus(text = '', error = false) {
    const status = $('library-status');
    status.textContent = text;
    status.classList.toggle('library-error', error);
    status.classList.toggle('hidden', !text);
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  }

  function coverPlaceholder() {
    return document.createElement('span');
  }

  function createCover(urls = []) {
    const cover = document.createElement('div');
    cover.className = 'library-cover';
    cover.setAttribute('aria-hidden', 'true');

    for (let index = 0; index < 4; index += 1) {
      const url = urls[index];
      if (!url) {
        cover.append(coverPlaceholder());
        continue;
      }
      const image = document.createElement('img');
      image.src = url;
      image.alt = '';
      image.loading = 'lazy';
      image.addEventListener('error', () => image.replaceWith(coverPlaceholder()), {once: true});
      cover.append(image);
    }
    return cover;
  }

  async function openPlaylist(item, link) {
    const previousText = link.textContent;
    link.textContent = 'Opening…';
    link.setAttribute('aria-busy', 'true');
    link.classList.add('is-loading');
    try {
      const record = await readJson(await fetch(`${ENDPOINT}/${encodeURIComponent(item.id)}`, {
        cache: 'no-store',
      }));
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        ...record.playlist,
        library_id: record.id,
      }));
      if (record.generation_request) {
        sessionStorage.setItem(REQUEST_KEY, JSON.stringify(record.generation_request));
      } else {
        sessionStorage.removeItem(REQUEST_KEY);
      }
      window.location.assign('/static/playlist.html');
    } catch (error) {
      link.textContent = previousText;
      link.removeAttribute('aria-busy');
      link.classList.remove('is-loading');
      setStatus(error.message || String(error), true);
    }
  }

  async function duplicatePlaylist(item, button) {
    const reset = setLoadingButton(button, {label: 'Duplicating', resetText: 'Duplicate'});
    try {
      await readJson(await fetch(`${ENDPOINT}/${encodeURIComponent(item.id)}/duplicate`, {
        method: 'POST',
      }));
      await loadLibrary();
    } catch (error) {
      reset();
      setStatus(error.message || String(error), true);
    }
  }

  async function deletePlaylist(item, button) {
    if (!window.confirm(`Delete “${item.name}” from the local library?`)) return;
    const reset = setLoadingButton(button, {label: 'Deleting', resetText: 'Delete'});
    try {
      const response = await fetch(`${ENDPOINT}/${encodeURIComponent(item.id)}`, {
        method: 'DELETE',
      });
      if (!response.ok) await readJson(response);
      const current = (() => {
        try {
          return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
        } catch {
          return null;
        }
      })();
      if (current?.library_id === item.id) {
        sessionStorage.removeItem(STORAGE_KEY);
        sessionStorage.removeItem(REQUEST_KEY);
      }
      await loadLibrary();
    } catch (error) {
      reset();
      setStatus(error.message || String(error), true);
    }
  }

  function createLibraryItem(item) {
    const card = document.createElement('article');
    card.className = 'library-item';
    card.append(createCover(item.thumbnail_urls));

    const copy = document.createElement('div');
    copy.className = 'library-copy';

    const titleRow = document.createElement('div');
    titleRow.className = 'library-title-row';
    const title = document.createElement('strong');
    title.className = 'library-title';
    title.textContent = item.name || 'Untitled playlist';
    title.title = title.textContent;
    const badge = document.createElement('span');
    badge.className = `library-status-badge ${item.status === 'published' ? 'published' : ''}`;
    badge.textContent = item.status === 'published' ? 'Published' : 'Draft';
    titleRow.append(title, badge);

    const description = document.createElement('p');
    description.className = 'library-description';
    description.textContent = item.description || item.prompt || 'No description saved.';

    const meta = document.createElement('p');
    meta.className = 'library-meta';
    const trackLabel = `${item.track_count} ${item.track_count === 1 ? 'track' : 'tracks'}`;
    meta.textContent = [trackLabel, `Updated ${formatDate(item.updated_at)}`].filter(Boolean).join(' · ');

    copy.append(titleRow, description, meta);

    const actions = document.createElement('div');
    actions.className = 'library-actions';

    const open = document.createElement('a');
    open.href = `/static/playlist.html?id=${encodeURIComponent(item.id)}`;
    open.className = 'primary';
    open.textContent = 'Open';
    open.addEventListener('click', (event) => {
      event.preventDefault();
      void openPlaylist(item, open);
    });

    const duplicate = document.createElement('button');
    duplicate.type = 'button';
    duplicate.className = 'secondary';
    duplicate.textContent = 'Duplicate';
    duplicate.addEventListener('click', () => void duplicatePlaylist(item, duplicate));

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary library-delete';
    remove.textContent = 'Delete';
    remove.addEventListener('click', () => void deletePlaylist(item, remove));

    actions.append(open, duplicate, remove);

    if (item.youtube_playlist_url) {
      const youtube = document.createElement('a');
      youtube.href = item.youtube_playlist_url;
      youtube.target = '_blank';
      youtube.rel = 'noopener noreferrer';
      youtube.className = 'secondary';
      youtube.textContent = 'YouTube Music';
      actions.insertBefore(youtube, duplicate);
    }

    card.append(copy, actions);
    return card;
  }

  async function loadLibrary() {
    setStatus('Loading playlists…');
    $('library-empty').classList.add('hidden');
    try {
      const sort = $('library-sort').value;
      const payload = await readJson(await fetch(`${ENDPOINT}?sort=${encodeURIComponent(sort)}`, {
        cache: 'no-store',
      }));
      const items = Array.isArray(payload.items) ? payload.items : [];
      $('library-list').replaceChildren(...items.map(createLibraryItem));
      $('library-empty').classList.toggle('hidden', items.length > 0);
      setStatus('');
    } catch (error) {
      $('library-list').replaceChildren();
      setStatus(error.message || String(error), true);
    }
  }

  $('library-sort').addEventListener('change', () => void loadLibrary());
  void loadLibrary();
})();
