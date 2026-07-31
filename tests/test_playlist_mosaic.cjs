'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  TILE_COUNT,
  representativeIndexes,
  selectMosaicUrls,
} = require('../frontend/playlist-mosaic.js');

function tracksWithUrls(urls) {
  return urls.map((thumbnail_url) => ({thumbnail_url}));
}

test('representative indexes cover the full playlist', () => {
  assert.deepEqual(representativeIndexes(0), []);
  assert.deepEqual(representativeIndexes(1), [0]);
  assert.deepEqual(representativeIndexes(5), [0, 1, 3, 4]);
  assert.deepEqual(representativeIndexes(10), [0, 3, 6, 9]);
});

test('mosaic uses four representative thumbnails', () => {
  const tracks = tracksWithUrls(Array.from({length: 10}, (_, index) => `url-${index}`));

  assert.equal(TILE_COUNT, 4);
  assert.deepEqual(selectMosaicUrls(tracks), [
    'url-0',
    'url-3',
    'url-6',
    'url-9',
  ]);
});

test('missing representative thumbnails are filled from the remaining playlist', () => {
  const tracks = tracksWithUrls(Array.from({length: 10}, (_, index) => `url-${index}`));
  tracks[3].thumbnail_url = '';

  assert.deepEqual(selectMosaicUrls(tracks), [
    'url-0',
    'url-6',
    'url-9',
    'url-1',
  ]);
});

test('duplicate and blank thumbnail URLs are ignored', () => {
  const tracks = tracksWithUrls(['same', ' same ', '', 'other', 'third', 'fourth']);

  assert.deepEqual(selectMosaicUrls(tracks), [
    'same',
    'other',
    'fourth',
    'third',
  ]);
});

test('invalid input returns an empty mosaic', () => {
  assert.deepEqual(selectMosaicUrls(null), []);
  assert.deepEqual(selectMosaicUrls({}), []);
});
