'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'youtube-account.js'),
  'utf8',
);

test('OAuth polling failures re-enable connection retry', () => {
  assert.match(source, /function allowConnectionRetry\(\)/);
  const calls = source.match(/allowConnectionRetry\(\);/g) || [];
  assert.ok(calls.length >= 2);
  assert.match(source, /connect\.disabled = false;/);
});
