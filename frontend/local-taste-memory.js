(() => {
  'use strict';

  const ENDPOINT = '/api/quality/local-feedback';
  const list = document.getElementById('taste-memory-list');
  const empty = document.getElementById('taste-memory-empty');
  if (!list || !empty) return;
  const {readJson} = window.PlaylistMuseCommon;

  const STATUS_LABELS = {
    pending: 'Still processing...',
    captured: null,
    distillation_failed: 'Could not be generated',
  };

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

    const meta = document.createElement('p');
    meta.className = 'taste-memory-meta';
    const tagCount = counts.get(tagKey(entry.tags)) || 0;
    const parts = [new Date(entry.created_at).toLocaleDateString()];
    if (tagCount > 1) parts.push(`seen ${tagCount} times`);
    meta.textContent = parts.join(' · ');
    body.append(meta);

    row.append(body);

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'taste-memory-delete';
    remove.setAttribute('aria-label', 'Forget this entry');
    remove.textContent = 'Forget';
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try {
        await fetch(`${ENDPOINT}/${encodeURIComponent(entry.id)}`, {method: 'DELETE'});
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
    }

    entries.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    const counts = groupCounts(entries);
    list.replaceChildren(...entries.map((entry) => entryRow(entry, counts)));
    empty.classList.toggle('hidden', entries.length > 0);
  }

  document.querySelector('[data-stats-section="taste"]')?.addEventListener('click', render);
  if (new URLSearchParams(window.location.search).get('section') === 'taste') render();
})();
