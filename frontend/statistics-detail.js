(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const {readJson} = window.PlaylistMuseCommon;
  const {renderRankList} = window.PlaylistMuseStatsRender;

  const DIMENSIONS = {
    genres: {title: 'All genres', key: 'top_genres', empty: 'No tagged playlists yet.'},
    artists: {title: 'All artists', key: 'top_artists', empty: 'No saved playlists yet.'},
    moods: {title: 'All moods', key: 'top_moods', empty: 'No tagged playlists yet.'},
    periods: {title: 'All periods', key: 'top_periods', empty: 'No tagged playlists yet.'},
  };

  function currentDimension() {
    const value = new URLSearchParams(window.location.search).get('dim');
    return DIMENSIONS[value] ? value : 'genres';
  }

  async function loadDetail() {
    const dim = currentDimension();
    const config = DIMENSIONS[dim];

    document.title = `${config.title} · PlaylistMuse`;
    $('stats-detail-title').textContent = config.title;

    try {
      const data = await readJson(await fetch('/api/stats', {cache: 'no-store'}));
      const items = (data.general || {})[config.key] || [];

      $('stats-detail-empty').textContent = config.empty;
      renderRankList('stats-detail-list', 'stats-detail-empty', items);

      $('stats-detail-status').classList.add('hidden');
      $('stats-detail-content').classList.remove('hidden');
    } catch (error) {
      $('stats-detail-status').textContent = error.message || 'Statistics are unavailable right now.';
      $('stats-detail-status').classList.add('error');
    }
  }

  void loadDetail();
})();
