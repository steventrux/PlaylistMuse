(function (root, factory) {
  'use strict';

  const api = factory();

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PlaylistMuseMosaic = api;
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  'use strict';

  const TILE_COUNT = 4;

  function representativeIndexes(length) {
    const count = Number.isInteger(length) && length > 0 ? length : 0;
    if (!count) return [];

    const last = count - 1;
    return [...new Set([
      0,
      Math.round(last / 3),
      Math.round((last * 2) / 3),
      last,
    ])];
  }

  function thumbnailUrl(track) {
    return typeof track?.thumbnail_url === 'string'
      ? track.thumbnail_url.trim()
      : '';
  }

  function selectMosaicUrls(tracks, tileCount = TILE_COUNT) {
    const list = Array.isArray(tracks) ? tracks : [];
    const limit = Number.isInteger(tileCount) && tileCount > 0
      ? tileCount
      : TILE_COUNT;
    const representativeTracks = representativeIndexes(list.length)
      .map((index) => list[index]);
    const orderedTracks = [...representativeTracks, ...list];
    const urls = [];

    for (const track of orderedTracks) {
      const url = thumbnailUrl(track);
      if (!url || urls.includes(url)) continue;

      urls.push(url);
      if (urls.length === limit) break;
    }

    return urls;
  }

  return Object.freeze({
    TILE_COUNT,
    representativeIndexes,
    selectMosaicUrls,
  });
}));
