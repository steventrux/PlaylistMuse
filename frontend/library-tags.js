(() => {
  'use strict';

  const LIMITS = {genre: 3, mood: 2, period: 1};
  const FILTER_IDS = {
    genre: 'library-genre-filter',
    mood: 'library-mood-filter',
    period: 'library-period-filter',
  };

  function clean(value) {
    return String(value || '').trim().replace(/\s+/g, ' ');
  }

  function valuesFor(tags, category) {
    const values = Array.isArray(tags?.[category]) ? tags[category] : [];
    const seen = new Set();
    return values
      .map(clean)
      .filter((value) => {
        const key = value.toLocaleLowerCase();
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
    };
  }

  function hasTags(tags) {
    return Object.values(normalize(tags)).some((values) => values.length);
  }

  function searchValues(item) {
    const tags = normalize(item?.tags);
    return [...tags.genre, ...tags.mood, ...tags.period];
  }

  function chip(label, value) {
    const element = document.createElement('span');
    element.className = 'library-tag-chip';
    element.textContent = `${label}: ${value}`;
    return element;
  }

  function summary(item) {
    const tags = normalize(item?.tags);
    if (!hasTags(tags)) return null;

    const container = document.createElement('div');
    container.className = 'library-tags';
    tags.genre.forEach((value) => container.append(chip('Genre', value)));
    tags.mood.forEach((value) => container.append(chip('Mood', value)));
    tags.period.forEach((value) => container.append(chip('Period', value)));
    return container;
  }

  function filterValue(category) {
    return clean(document.getElementById(FILTER_IDS[category])?.value).toLocaleLowerCase();
  }

  function matchesFilters(item) {
    const tags = normalize(item?.tags);
    return Object.keys(FILTER_IDS).every((category) => {
      const selected = filterValue(category);
      if (!selected) return true;
      return tags[category].some((value) => value.toLocaleLowerCase() === selected);
    });
  }

  function categoryOptions(items, category) {
    const values = new Map();
    items.forEach((item) => {
      valuesFor(item?.tags, category).forEach((value) => {
        const key = value.toLocaleLowerCase();
        if (!values.has(key)) values.set(key, value);
      });
    });
    return [...values.values()].sort((left, right) => left.localeCompare(right));
  }

  function refreshSelect(select, values) {
    if (!select) return;
    const previous = select.value;
    const first = select.options[0]?.cloneNode(true);
    select.replaceChildren();
    if (first) select.append(first);
    values.forEach((value) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.append(option);
    });
    if ([...select.options].some((option) => option.value === previous)) {
      select.value = previous;
    }
  }

  function refreshFilters(items) {
    Object.entries(FILTER_IDS).forEach(([category, id]) => {
      refreshSelect(document.getElementById(id), categoryOptions(items, category));
    });
  }

  function bindFilters(render) {
    Object.values(FILTER_IDS).forEach((id) => {
      document.getElementById(id)?.addEventListener('change', render);
    });
  }

  function parseList(value, category) {
    const values = [];
    const seen = new Set();
    String(value || '').split(',').forEach((part) => {
      const tag = clean(part);
      const key = tag.toLocaleLowerCase();
      if (!tag || seen.has(key)) return;
      if (tag.length > 48) throw new Error('Tags must be 48 characters or fewer.');
      seen.add(key);
      values.push(tag);
    });
    if (values.length > LIMITS[category]) {
      throw new Error(
        `${category[0].toUpperCase()}${category.slice(1)} supports at most ${LIMITS[category]} ${LIMITS[category] === 1 ? 'tag' : 'tags'}.`,
      );
    }
    return values;
  }

  function field(labelText, value, {placeholder = '', single = false} = {}) {
    const label = document.createElement('label');
    label.className = 'library-tag-field';
    const text = document.createElement('span');
    text.textContent = labelText;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = value;
    input.placeholder = placeholder;
    input.autocomplete = 'off';
    if (single) input.dataset.singleTag = 'true';
    label.append(text, input);
    return {label, input};
  }

  function install({item, detailGrid, reload, setStatus, readJson, endpoint}) {
    const tags = normalize(item?.tags);
    const block = document.createElement('section');
    block.className = 'library-detail-block library-tags-editor';

    const heading = document.createElement('h3');
    heading.textContent = 'Tags';
    const hint = document.createElement('p');
    hint.className = 'library-tag-hint';
    hint.textContent = 'Genre up to 3 · Mood up to 2 · Period 1';

    const fields = document.createElement('div');
    fields.className = 'library-tag-fields';
    const genre = field('Genre', tags.genre.join(', '), {placeholder: 'Rock, Blues Rock'});
    const mood = field('Mood', tags.mood.join(', '), {placeholder: 'Energetic, Atmospheric'});
    const period = field('Period', tags.period[0] || '', {placeholder: '1970s–1980s', single: true});
    fields.append(genre.label, mood.label, period.label);

    const actions = document.createElement('div');
    actions.className = 'library-tag-actions';
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'secondary';
    save.textContent = 'Save tags';
    const suggest = document.createElement('button');
    suggest.type = 'button';
    suggest.className = 'secondary';
    suggest.textContent = hasTags(tags) ? 'Suggest again' : 'Suggest with AI';
    actions.append(save, suggest);

    save.addEventListener('click', async (event) => {
      event.stopPropagation();
      try {
        const nextTags = {
          genre: parseList(genre.input.value, 'genre'),
          mood: parseList(mood.input.value, 'mood'),
          period: parseList(period.input.value, 'period'),
        };
        save.disabled = true;
        suggest.disabled = true;
        setStatus('Saving playlist tags…');
        const record = await readJson(await fetch(
          `${endpoint}/${encodeURIComponent(item.id)}`,
          {cache: 'no-store'},
        ));
        record.playlist.tags = nextTags;
        await readJson(await fetch(`${endpoint}/${encodeURIComponent(item.id)}`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            playlist: record.playlist,
            generation_request: record.generation_request || null,
          }),
        }));
        await reload();
        setStatus('');
      } catch (error) {
        save.disabled = false;
        suggest.disabled = false;
        setStatus(error.message || String(error), true);
      }
    });

    suggest.addEventListener('click', async (event) => {
      event.stopPropagation();
      save.disabled = true;
      suggest.disabled = true;
      setStatus('Classifying playlist tags…');
      try {
        await readJson(await fetch(
          `${endpoint}/${encodeURIComponent(item.id)}/tags/suggest`,
          {method: 'POST'},
        ));
        await reload();
        setStatus('');
      } catch (error) {
        save.disabled = false;
        suggest.disabled = false;
        setStatus(error.message || String(error), true);
      }
    });

    block.append(heading, hint, fields, actions);
    detailGrid.append(block);
  }

  window.PlaylistMuseLibraryTags = {
    bindFilters,
    install,
    matchesFilters,
    normalize,
    refreshFilters,
    searchValues,
    summary,
  };
})();
