(() => {
  'use strict';

  const DEFAULT_PAGE_SIZE = 10;

  function positiveInteger(value, fallback) {
    const number = Number(value);
    return Number.isInteger(number) && number > 0 ? number : fallback;
  }

  function pageCount(totalItems, pageSize = DEFAULT_PAGE_SIZE) {
    const size = positiveInteger(pageSize, DEFAULT_PAGE_SIZE);
    const total = Math.max(0, Number(totalItems) || 0);
    return Math.ceil(total / size);
  }

  function clampPage(page, totalItems, pageSize = DEFAULT_PAGE_SIZE) {
    const totalPages = pageCount(totalItems, pageSize);
    if (!totalPages) return 1;
    return Math.min(positiveInteger(page, 1), totalPages);
  }

  function paginate(items, page = 1, pageSize = DEFAULT_PAGE_SIZE) {
    const source = Array.isArray(items) ? items : [];
    const size = positiveInteger(pageSize, DEFAULT_PAGE_SIZE);
    const totalPages = pageCount(source.length, size);
    const currentPage = clampPage(page, source.length, size);
    const start = (currentPage - 1) * size;
    return {
      items: source.slice(start, start + size),
      currentPage,
      totalPages,
      totalItems: source.length,
    };
  }

  function pageTokens(currentPage, totalPages) {
    const total = Math.max(0, Number(totalPages) || 0);
    if (total <= 7) return Array.from({length: total}, (_, index) => index + 1);

    const current = Math.min(Math.max(1, positiveInteger(currentPage, 1)), total);
    const pages = new Set([1, total, current - 1, current, current + 1]);
    if (current <= 4) [2, 3, 4, 5].forEach((page) => pages.add(page));
    if (current >= total - 3) {
      [total - 4, total - 3, total - 2, total - 1].forEach((page) => pages.add(page));
    }

    const sorted = [...pages]
      .filter((page) => page >= 1 && page <= total)
      .sort((left, right) => left - right);
    const tokens = [];
    sorted.forEach((page, index) => {
      const previous = sorted[index - 1];
      if (previous && page - previous > 1) tokens.push('ellipsis');
      tokens.push(page);
    });
    return tokens;
  }

  const api = Object.freeze({
    DEFAULT_PAGE_SIZE,
    pageCount,
    clampPage,
    paginate,
    pageTokens,
  });

  if (typeof window !== 'undefined') window.PlaylistMuseLibraryPagination = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
