(() => {
  'use strict';

  const ENDPOINT = '/api/quality/local-feedback';
  const list = document.getElementById('taste-memory-list');
  const empty = document.getElementById('taste-memory-empty');
  const statusEl = document.getElementById('taste-memory-status');
  if (!list || !empty) return;
  const {readJson} = window.PlaylistMuseCommon;

  const STATUS_LABELS = {
    pending: 'Still processing…',
    captured: null,
    distillation_failed: 'Could not be generated',
  };

  const PROMPT_PREVIEW_LIMIT = 120;

  function truncatedPrompt(promptSummary) {
    const text = String(promptSummary || '').trim();
    if (text.length <= PROMPT_PREVIEW_LIMIT) return text;
    return `${text.slice(0, PROMPT_PREVIEW_LIMIT)}…`;
  }

  function tagKey(tags) {
    const values = [
      ...(tags?.genre || []),
      ...(tags?.mood || []),
    ].map((value) => String(value).toLocaleLowerCase());
    return values.sort().join('|');
  }

  function groupCounts(entries) {
    const counts = new Map();
    entries.forEach((entry) => {
      const key = tagKey(entry.tags);
      if (!key) return;
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return counts;
  }

  function entryRow(entry, counts) {
    const row = document.createElement('div');
    row.className = 'taste-memory-item';

    const body = document.createElement('div');
    body.className = 'taste-memory-body';

    const statusLabel = STATUS_LABELS[entry.status];
    const guidance = document.createElement('p');
    guidance.className = 'taste-memory-guidance';
    guidance.textContent = entry.distilled_guidance || statusLabel || 'Nothing notable beyond what you already asked for.';
    body.append(guidance);

    const promptText = truncatedPrompt(entry.prompt_summary);
    if (promptText) {
      const prompt = document.createElement('p');
      prompt.className = 'taste-memory-prompt';
      prompt.textContent = promptText;
      body.append(prompt);
    }

    const genreMoodTags = [
      ...(entry.tags?.genre || []),
      ...(entry.tags?.mood || []),
    ];
    if (genreMoodTags.length) {
      const tagRow = document.createElement('div');
      tagRow.className = 'taste-memory-tags';
      genreMoodTags.forEach((tag) => {
        const chip = document.createElement('span');
        chip.className = 'taste-memory-tag-chip';
        chip.textContent = tag;
        tagRow.append(chip);
      });
      body.append(tagRow);
    }

    const meta = document.createElement('p');
    meta.className = 'taste-memory-meta';
    const tagCount = counts.get(tagKey(entry.tags)) || 0;
    const parts = [new Date(entry.created_at).toLocaleDateString()];
    if (tagCount > 1) parts.push(`seen ${tagCount} times`);
    meta.textContent = parts.join(' · ');
    body.append(meta);

    row.append(body);

    if (entry.status === 'distillation_failed') {
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'taste-memory-retry';
      retry.setAttribute('aria-label', 'Retry generating guidance for this entry');
      retry.textContent = 'Retry';
      retry.addEventListener('click', async () => {
        retry.disabled = true;
        try {
          const response = await fetch(`${ENDPOINT}/${encodeURIComponent(entry.id)}/retry`, {method: 'POST'});
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          await render();
        } catch (error) {
          retry.disabled = false;
          console.warn('Could not retry taste memory entry:', error);
        }
      });
      row.append(retry);
    }

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'taste-memory-delete';
    remove.setAttribute('aria-label', 'Forget this entry');
    remove.textContent = 'Forget';
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try {
        const response = await fetch(`${ENDPOINT}/${encodeURIComponent(entry.id)}`, {method: 'DELETE'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await render();
      } catch (error) {
        remove.disabled = false;
        console.warn('Could not remove taste memory entry:', error);
      }
    });
    row.append(remove);

    return row;
  }

  async function render() {
    let entries = [];
    try {
      const payload = await readJson(await fetch(ENDPOINT, {cache: 'no-store'}));
      entries = Array.isArray(payload.entries) ? payload.entries : [];
    } catch (error) {
      console.warn('Could not load taste memory:', error);
      list.replaceChildren();
      list.classList.add('hidden');
      empty.classList.add('hidden');
      if (statusEl) {
        statusEl.textContent = error.message || 'Taste memory is unavailable right now.';
        statusEl.classList.remove('hidden');
        statusEl.classList.add('error');
      }
      return;
    }

    if (statusEl) {
      statusEl.classList.add('hidden');
      statusEl.classList.remove('error');
    }
    list.classList.remove('hidden');
    entries.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    const counts = groupCounts(entries);
    list.replaceChildren(...entries.map((entry) => entryRow(entry, counts)));
    empty.classList.toggle('hidden', entries.length > 0);
  }

  async function initGenerationInfluenceToggle() {
    const label = document.createElement('label');
    label.className = 'taste-memory-influence-toggle';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = 'taste-memory-generation-influence';

    label.append(checkbox, document.createTextNode(' Let converged taste memory patterns influence future generations'));
    list.before(label);

    try {
      const payload = await readJson(await fetch(`${ENDPOINT}/settings`, {cache: 'no-store'}));
      checkbox.checked = Boolean(payload.generation_influence_enabled);
    } catch (error) {
      console.warn('Could not load taste memory settings:', error);
      checkbox.checked = true;
    }

    checkbox.addEventListener('change', async () => {
      const nextValue = checkbox.checked;
      checkbox.disabled = true;
      try {
        await readJson(await fetch(`${ENDPOINT}/settings`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({generation_influence_enabled: nextValue}),
        }));
      } catch (error) {
        checkbox.checked = !nextValue;
        console.warn('Could not update taste memory settings:', error);
      } finally {
        checkbox.disabled = false;
      }
    });
  }

  initGenerationInfluenceToggle();
  document.querySelector('[data-stats-section="taste"]')?.addEventListener('click', render);
  if (new URLSearchParams(window.location.search).get('section') === 'taste') render();
})();
