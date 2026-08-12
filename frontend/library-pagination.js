(() => {
  'use strict';

  const DEFAULT_PAGE_SIZE = 10;
  const DEFAULT_VISIBLE_PAGES = 5;

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

  function pageTokens(currentPage, totalPages, maxVisible = DEFAULT_VISIBLE_PAGES) {
    const total = Math.max(0, Number(totalPages) || 0);
    if (!total) return [];

    const visible = Math.min(positiveInteger(maxVisible, DEFAULT_VISIBLE_PAGES), total);
    const current = Math.min(Math.max(1, positiveInteger(currentPage, 1)), total);
    const before = Math.floor((visible - 1) / 2);
    let start = current - before;
    let end = start + visible - 1;

    if (start < 1) {
      start = 1;
      end = visible;
    }
    if (end > total) {
      end = total;
      start = total - visible + 1;
    }

    return Array.from({length: visible}, (_, index) => start + index);
  }

  const api = Object.freeze({
    DEFAULT_PAGE_SIZE,
    DEFAULT_VISIBLE_PAGES,
    pageCount,
    clampPage,
    paginate,
    pageTokens,
  });

  if (typeof window !== 'undefined') window.PlaylistMuseLibraryPagination = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
