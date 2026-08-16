(() => {
  'use strict';

  const numberFormatter = new Intl.NumberFormat('en-US');

  function formatCount(value) {
    return numberFormatter.format(Number(value) || 0);
  }

  function toggleEmpty(emptyId, isEmpty) {
    const empty = document.getElementById(emptyId);
    if (empty) empty.classList.toggle('hidden', !isEmpty);
  }

  function renderRankList(listId, emptyId, items) {
    const list = document.getElementById(listId);
    if (!list) return;
    list.replaceChildren();

    items.forEach((item, index) => {
      const row = document.createElement('li');
      row.className = 'stats-rank-row';

      const rank = document.createElement('span');
      rank.className = 'stats-rank-index';
      rank.textContent = String(index + 1);

      const label = document.createElement('span');
      label.className = 'stats-rank-label';
      label.textContent = item.label;

      const count = document.createElement('span');
      count.className = 'stats-rank-count';
      count.textContent = formatCount(item.count);

      row.append(rank, label, count);
      list.append(row);
    });

    toggleEmpty(emptyId, items.length === 0);
  }

  window.PlaylistMuseStatsRender = Object.freeze({formatCount, renderRankList});
})();
