(() => {
  'use strict';

  const LIMITS = {genre: 3, mood: 2, period: 1, custom: 20};
  const AI_CATEGORIES = ['genre', 'mood', 'period'];
  const activeTagFilters = new Set();
  let renderLibrary = null;
  let reloadLibrary = null;
  let setLibraryStatus = null;
  let readJson = null;
  let endpoint = '';

  function clean(value) {
    return String(value || '').trim().replace(/\s+/g, ' ');
  }

  function keyFor(value) {
    return clean(value).toLocaleLowerCase();
  }

  function valuesFor(tags, category) {
    const values = Array.isArray(tags?.[category]) ? tags[category] : [];
    const seen = new Set();
    return values
      .map(clean)
      .filter((value) => {
        const key = keyFor(value);
        if (!value || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, LIMITS[category]);
  }

  function normalize(tags) {
    return {
      genre: valuesFor(tags, 'genre'),
      mood: valuesFor(tags, 'mood'),
      period: valuesFor(tags, 'period'),
      custom: valuesFor(tags, 'custom'),
    };
  }

  function searchValues(item) {
    const tags = normalize(item?.tags);
    return [...tags.genre, ...tags.mood, ...tags.period, ...tags.custom];
  }

  function matchesFilters(item) {
    if (!activeTagFilters.size) return true;
    const itemTags = new Set(searchValues(item).map(keyFor));
    return [...activeTagFilters].every((tag) => itemTags.has(tag));
  }

  function refreshFilters(items) {
    const available = new Set(
      items.flatMap((item) => searchValues(item)).map(keyFor),
    );
    [...activeTagFilters].forEach((tag) => {
      if (!available.has(tag)) activeTagFilters.delete(tag);
    });
  }

  function bindFilters(render) {
    renderLibrary = render;
  }

  function toggleFilter(value) {
    const key = keyFor(value);
    if (!key) return;
    if (activeTagFilters.has(key)) {
      activeTagFilters.delete(key);
    } else {
      activeTagFilters.add(key);
    }
    renderLibrary?.();
  }

  function tagChip(value, {category = '', personal = false, filterable = true} = {}) {
    const element = document.createElement(filterable ? 'button' : 'span');
    if (filterable) element.type = 'button';
    element.className = `library-tag-chip${personal ? ' library-tag-personal-value' : ''}`;
    element.textContent = value;
    element.dataset.tagValue = value;
    if (category) element.dataset.tagCategory = category;
    element.title = category
      ? `${category[0].toUpperCase()}${category.slice(1)}: ${value}`
      : `Personal tag: ${value}`;

    if (filterable) {
      const active = activeTagFilters.has(keyFor(value));
      element.classList.toggle('active', active);
      element.setAttribute('aria-pressed', String(active));
      element.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleFilter(value);
      });
    }
    return element;
  }

  function plusIcon() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"/></svg>';
  }

  function checkIcon() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m5 12 4 4L19 6"/></svg>';
  }

  function trashIcon() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5"/></svg>';
  }

  function addPersonal(tags, value) {
    const next = normalize(tags);
    const label = clean(value);
    if (!label) throw new Error('Enter a tag first.');
    if (label.length > 48) throw new Error('Tags must be 48 characters or fewer.');

    const existing = new Set(
      [...next.genre, ...next.mood, ...next.period, ...next.custom].map(keyFor),
    );
    if (existing.has(keyFor(label))) throw new Error('This tag already exists.');
    if (next.custom.length >= LIMITS.custom) {
      throw new Error(`A playlist can have at most ${LIMITS.custom} personal tags.`);
    }
    next.custom.push(label);
    return next;
  }

  function removePersonal(tags, value) {
    const next = normalize(tags);
    const key = keyFor(value);
    next.custom = next.custom.filter((tag) => keyFor(tag) !== key);
    return next;
  }

  async function updatePersonalTags(item, transform, statusText) {
    if (!readJson || !endpoint || !reloadLibrary) {
      throw new Error('Playlist tag controls are not ready yet.');
    }
    setLibraryStatus?.(statusText);
    const record = await readJson(await fetch(
      `${endpoint}/${encodeURIComponent(item.id)}`,
      {cache: 'no-store'},
    ));
    record.playlist.tags = transform(record.playlist?.tags);
    await readJson(await fetch(`${endpoint}/${encodeURIComponent(item.id)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        playlist: record.playlist,
        generation_request: record.generation_request || null,
      }),
    }));
    await reloadLibrary();
    setLibraryStatus?.('');
  }

  async function addPersonalTag(item, value) {
    await updatePersonalTags(
      item,
      (tags) => addPersonal(tags, value),
      'Adding personal tag…',
    );
  }

  async function removePersonalTag(item, value) {
    await updatePersonalTags(
      item,
      (tags) => removePersonal(tags, value),
      'Removing personal tag…',
    );
  }

  function personalChip(value, {filterable, onRemove, onError}) {
    const wrapper = document.createElement('span');
    wrapper.className = 'library-personal-tag';
    wrapper.append(tagChip(value, {personal: true, filterable}));

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'library-tag-delete';
    remove.innerHTML = trashIcon();
    remove.setAttribute('aria-label', `Delete personal tag ${value}`);
    remove.title = 'Delete personal tag';
    remove.addEventListener('click', async (event) => {
      event.stopPropagation();
      remove.disabled = true;
      try {
        await onRemove(value);
      } catch (error) {
        remove.disabled = false;
        onError?.(error);
      }
    });
    wrapper.append(remove);
    return wrapper;
  }

  function openAddForm(container, addButtonElement, onAdd, onError) {
    const existing = container.querySelector('.library-tag-add-form');
    if (existing) {
      existing.querySelector('input')?.focus();
      return;
    }

    const form = document.createElement('form');
    form.className = 'library-tag-add-form';
    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 48;
    input.autocomplete = 'off';
    input.placeholder = 'Personal tag';
    input.setAttribute('aria-label', 'New personal tag');

    const confirm = document.createElement('button');
    confirm.type = 'submit';
    confirm.className = 'library-tag-confirm';
    confirm.innerHTML = checkIcon();
    confirm.setAttribute('aria-label', 'Add personal tag');
    confirm.title = 'Add tag';

    function close() {
      form.remove();
      addButtonElement.hidden = false;
    }

    input.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      close();
      addButtonElement.focus();
    });

    form.addEventListener('focusout', () => {
      window.setTimeout(() => {
        if (!form.isConnected || form.contains(document.activeElement)) return;
        if (!clean(input.value)) close();
      }, 0);
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const label = clean(input.value);
      if (!label) {
        close();
        return;
      }
      input.disabled = true;
      confirm.disabled = true;
      try {
        await onAdd(label);
        close();
      } catch (error) {
        input.disabled = false;
        confirm.disabled = false;
        onError?.(error);
        input.focus();
      }
    });

    form.addEventListener('click', (event) => event.stopPropagation());
    form.append(input, confirm);
    addButtonElement.hidden = true;
    addButtonElement.insertAdjacentElement('afterend', form);
    input.focus();
  }

  function addButton(container, onAdd, onError) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'library-tag-add';
    button.innerHTML = plusIcon();
    button.setAttribute('aria-label', 'Add a personal tag');
    button.title = 'Add personal tag';
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      openAddForm(container, button, onAdd, onError);
    });
    return button;
  }

  function renderTags(tagsValue, {
    filterable = true,
    onAddPersonal,
    onRemovePersonal,
    onError,
  } = {}) {
    const tags = normalize(tagsValue);
    const container = document.createElement('div');
    container.className = 'library-tags';

    const aiGroup = document.createElement('span');
    aiGroup.className = 'library-tag-ai-group';
    AI_CATEGORIES.forEach((category) => {
      tags[category].forEach((value) => {
        aiGroup.append(tagChip(value, {category, filterable}));
      });
    });

    const personalGroup = document.createElement('span');
    personalGroup.className = 'library-tag-personal-group';
    if (onRemovePersonal) {
      tags.custom.forEach((value) => personalGroup.append(personalChip(value, {
        filterable,
        onRemove: onRemovePersonal,
        onError,
      })));
    } else {
      tags.custom.forEach((value) => personalGroup.append(tagChip(value, {
        personal: true,
        filterable,
      })));
    }

    container.append(aiGroup);
    if (onAddPersonal) container.append(addButton(container, onAddPersonal, onError));
    container.append(personalGroup);
    return container;
  }

  function summary(item) {
    return renderTags(item?.tags, {
      filterable: true,
      onAddPersonal: (value) => addPersonalTag(item, value),
      onRemovePersonal: (value) => removePersonalTag(item, value),
      onError: (error) => setLibraryStatus?.(error.message || String(error), true),
    });
  }

  function editableSummary(tags, options = {}) {
    return renderTags(tags, {
      ...options,
      filterable: false,
    });
  }

  function install({reload, setStatus, readJson: jsonReader, endpoint: apiEndpoint}) {
    reloadLibrary = reload;
    setLibraryStatus = setStatus;
    readJson = jsonReader;
    endpoint = apiEndpoint;
  }

  const api = {
    addPersonal,
    bindFilters,
    editableSummary,
    install,
    matchesFilters,
    normalize,
    refreshFilters,
    removePersonal,
    searchValues,
    summary,
  };
  window.PlaylistMuseTags = api;
  window.PlaylistMuseLibraryTags = api;
})();
