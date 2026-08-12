const test = require('node:test');
const assert = require('node:assert/strict');
const pagination = require('../frontend/library-pagination.js');

test('playlist pagination uses ten items per page by default', () => {
  const items = Array.from({length: 27}, (_, index) => index + 1);
  assert.equal(pagination.DEFAULT_PAGE_SIZE, 10);
  assert.equal(pagination.paginate(items, 1).totalPages, 3);
  assert.deepEqual(pagination.paginate(items, 1).items, items.slice(0, 10));
  assert.deepEqual(pagination.paginate(items, 2).items, items.slice(10, 20));
  assert.deepEqual(pagination.paginate(items, 3).items, items.slice(20, 27));
});

test('playlist pagination clamps the current page after the result set shrinks', () => {
  const items = Array.from({length: 20}, (_, index) => index + 1);
  const page = pagination.paginate(items, 3);
  assert.equal(page.currentPage, 2);
  assert.equal(page.totalPages, 2);
  assert.deepEqual(page.items, items.slice(10, 20));
});

test('desktop pagination shows at most five consecutive page numbers', () => {
  assert.equal(pagination.DEFAULT_VISIBLE_PAGES, 5);
  assert.deepEqual(pagination.pageTokens(1, 20, 5), [1, 2, 3, 4, 5]);
  assert.deepEqual(pagination.pageTokens(10, 20, 5), [8, 9, 10, 11, 12]);
  assert.deepEqual(pagination.pageTokens(20, 20, 5), [16, 17, 18, 19, 20]);
});

test('mobile pagination can be limited to three consecutive page numbers', () => {
  assert.deepEqual(pagination.pageTokens(1, 20, 3), [1, 2, 3]);
  assert.deepEqual(pagination.pageTokens(10, 20, 3), [9, 10, 11]);
  assert.deepEqual(pagination.pageTokens(20, 20, 3), [18, 19, 20]);
});

test('pagination never pads the page window beyond the available pages', () => {
  assert.deepEqual(pagination.pageTokens(2, 3, 5), [1, 2, 3]);
  assert.deepEqual(pagination.pageTokens(1, 0, 5), []);
});
