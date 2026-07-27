(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function setStatus(text = '', error = false) {
    $('status').textContent = text;
    $('status').classList.toggle('error', error);
  }

  async function readJson(response) {
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; }
    catch { throw new Error(text || `HTTP ${response.status}`); }
    if (!response.ok) {
      const detail = data.detail ?? data.error ?? data.message;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || data));
    }
    return data;
  }

  function renderTracks(data) {
    $('playlist-name').textContent = data.name || 'Generated playlist';
    $('resolved-count').textContent = `${data.resolved_count}/${data.requested_count} resolved`;
    $('track-list').replaceChildren(...data.tracks.map((track, index) => {
      const item = document.createElement('li');
      item.className = 'track';

      const art = document.createElement('img');
      art.loading = 'lazy';
      art.alt = '';
      art.src = track.thumbnail_url || 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"/>';

      const text = document.createElement('div');
      text.className = 'track-copy';
      const title = document.createElement('strong');
      title.textContent = `${index + 1}. ${track.title}`;
      const meta = document.createElement('span');
      meta.textContent = [track.artists, track.album, track.duration].filter(Boolean).join(' · ');
      text.append(title, meta);

      const link = document.createElement('a');
      link.href = track.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Play';

      item.append(art, text, link);
      return item;
    }));
    $('results').classList.remove('hidden');
    $('results').scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  async function generate() {
    const prompt = $('prompt').value.trim().replace(/\s+/g, ' ');
    if (!prompt) return setStatus('Describe the playlist you want.', true);

    const button = $('generate');
    button.disabled = true;
    button.textContent = 'Generating…';
    setStatus('Curating tracks and resolving them on YouTube Music…');

    try {
      const data = await readJson(await fetch('/api/playlists/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          prompt,
          track_count: Math.max(5, Math.min(100, Number($('track-count').value) || 25)),
          options: {
            exclude_live: $('exclude-live').checked,
            exclude_covers: $('exclude-covers').checked,
            exclude_remixes: $('exclude-remixes').checked,
          },
        }),
      }));
      renderTracks(data);
      setStatus(data.resolved_count ? '' : 'No tracks could be resolved.', !data.resolved_count);
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      button.disabled = false;
      button.textContent = 'Generate playlist';
    }
  }

  async function loadSettings() {
    const data = await readJson(await fetch('/api/settings'));
    $('ai-provider').value = data.provider || 'gemini';
    $('ai-model').value = data.model || '';
    $('ai-base-url').value = data.base_url || '';
    $('settings-status').textContent = data.configured ? 'Provider configured.' : 'Configuration required.';
  }

  async function saveSettings() {
    const button = $('save-settings');
    button.disabled = true;
    try {
      const data = await readJson(await fetch('/api/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          provider: $('ai-provider').value,
          model: $('ai-model').value.trim(),
          api_key: $('ai-key').value.trim(),
          base_url: $('ai-base-url').value.trim(),
        }),
      }));
      $('ai-key').value = '';
      $('settings-status').textContent = data.configured ? 'Settings saved.' : 'Saved, but the provider is not fully configured.';
    } catch (error) {
      $('settings-status').textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  }

  $('generate').addEventListener('click', generate);
  $('settings-btn').addEventListener('click', async () => {
    $('settings-dialog').showModal();
    try { await loadSettings(); }
    catch (error) { $('settings-status').textContent = error.message || String(error); }
  });
  $('close-settings').addEventListener('click', () => $('settings-dialog').close());
  $('save-settings').addEventListener('click', saveSettings);
})();
