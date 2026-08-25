(() => {
  'use strict';

  const STORAGE_KEY = 'playlistmuse-generated-playlist';
  const REQUEST_KEY = 'playlistmuse-generation-request';
  const ISSUE_URL = 'https://github.com/steventrux/PlaylistMuse/issues/new';
  const FEEDBACK_LABEL = 'playlist feedback';
  const MAX_BODY_LENGTH = 7500;
  const button = document.getElementById('playlist-feedback');
  if (!button) return;

  function readStoredJson(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) || 'null');
    } catch {
      return null;
    }
  }

  function clean(value, maxLength = 2000) {
    return String(value || '').replace(/\r\n/g, '\n').trim().slice(0, maxLength);
  }

  function refinementPrompts(generationRequest) {
    const refinements = generationRequest?.refinements;
    if (!Array.isArray(refinements)) return [];
    return refinements
      .map((item) => clean(typeof item === 'string' ? item : item?.prompt, 1000))
      .filter(Boolean)
      .slice(-12);
  }

  function generationFlow(generationRequest, refinements) {
    if (refinements.length) return 'Playlist Studio refinement';
    if (generationRequest?.mode === 'seed') return 'Seed-track generation';
    if (generationRequest?.mode === 'journey') return 'Track-to-track journey generation';
    return 'Initial prompt generation';
  }

  function requestText(playlist, generationRequest) {
    if (generationRequest?.mode === 'prompt') {
      return clean(generationRequest.prompt || playlist?.prompt, 1950);
    }
    if (generationRequest?.mode === 'seed') {
      const seed = generationRequest.seed || {};
      const title = clean(seed.title, 300);
      const artists = clean(seed.artists || seed.artist, 300);
      const mode = clean(generationRequest.seed_mode, 80);
      return `Seed: ${title || 'Unknown track'} — ${artists || 'Unknown artist'}${mode ? `\nSimilarity mode: ${mode}` : ''}`;
    }
    if (generationRequest?.mode === 'journey') {
      const start = generationRequest.start || {};
      const end = generationRequest.end || {};
      const startText = `${clean(start.title, 300) || 'Unknown track'} — ${clean(start.artists, 300) || 'Unknown artist'}`;
      const endText = `${clean(end.title, 300) || 'Unknown track'} — ${clean(end.artists, 300) || 'Unknown artist'}`;
      return `Journey start: ${startText}\nJourney end: ${endText}`;
    }
    return clean(playlist?.prompt, 1950);
  }

  function optionContext(generationRequest) {
    const options = generationRequest?.options;
    if (!options || typeof options !== 'object') return '';
    const labels = [
      ['Exclude live tracks', options.exclude_live],
      ['Exclude covers', options.exclude_covers],
      ['Exclude remixes', options.exclude_remixes],
    ];
    return labels
      .filter(([, value]) => typeof value === 'boolean')
      .map(([label, value]) => `- ${label}: ${value ? 'on' : 'off'}`)
      .join('\n');
  }

  function trackLines(playlist) {
    const tracks = Array.isArray(playlist?.tracks) ? playlist.tracks : [];
    return tracks.slice(0, 100).map((track, index) => {
      const title = clean(track?.title || 'Unknown track', 300);
      const artists = clean(track?.artists || track?.artist || 'Unknown artist', 300);
      return `${index + 1}. ${artists} — ${title}`;
    });
  }

  function trimBody(body) {
    if (body.length <= MAX_BODY_LENGTH) return body;
    const suffix = '\n\n_The captured playlist context was truncated to keep the GitHub issue URL manageable._';
    return `${body.slice(0, MAX_BODY_LENGTH - suffix.length)}${suffix}`;
  }

  function issueBody(playlist, generationRequest) {
    const refinements = refinementPrompts(generationRequest);
    const flow = generationFlow(generationRequest, refinements);
    const request = requestText(playlist, generationRequest) || 'Not available';
    const tracks = trackLines(playlist);
    const options = optionContext(generationRequest);
    const lineage = refinements.length
      ? refinements.map((prompt, index) => `${index + 1}. ${prompt}`).join('\n')
      : 'No Playlist Studio refinements recorded.';

    return trimBody([
      '<!-- playlistmuse-feedback:v1 -->',
      '## What did not match your request?',
      '<!-- Describe the constraint, preference, quantity, ordering, artist, version, or other part that was not respected. -->',
      '',
      '## What did you expect instead?',
      '<!-- Describe the intended result as precisely as possible. -->',
      '',
      '## Captured request',
      `**Flow:** ${flow}`,
      '',
      request,
      '',
      '## Previous refinement context',
      lineage,
      '',
      '## Generation options',
      options || 'No generation filter context available.',
      '',
      `## Playlist result (${tracks.length} track${tracks.length === 1 ? '' : 's'} captured)`,
      tracks.join('\n') || 'No track list available.',
      '',
      '## Additional context',
      '<!-- Optional: screenshots or anything else that helps explain the expected musical behavior. -->',
      '',
      '---',
      '_This issue was prepared by PlaylistMuse. Review the captured prompt before submitting and remove personal or sensitive information._',
    ].join('\n'));
  }

  function openFeedback() {
    const playlist = readStoredJson(STORAGE_KEY);
    if (!playlist || !Array.isArray(playlist.tracks) || !playlist.tracks.length) return;
    const generationRequest = readStoredJson(REQUEST_KEY);
    const titleName = clean(playlist.name || 'playlist result', 80);
    const params = new URLSearchParams({
      title: `[Playlist feedback] ${titleName}`,
      labels: FEEDBACK_LABEL,
      body: issueBody(playlist, generationRequest),
    });
    window.open(`${ISSUE_URL}?${params.toString()}`, '_blank', 'noopener,noreferrer');
  }

  if (new URLSearchParams(window.location.search).has('id')) return;
  const playlist = readStoredJson(STORAGE_KEY);
  if (!playlist || !Array.isArray(playlist.tracks) || !playlist.tracks.length) return;

  button.classList.remove('hidden');
  button.addEventListener('click', openFeedback);
})();
