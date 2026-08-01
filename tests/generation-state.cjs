'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const generationState = require('../frontend/generation-state.js');

test('normalizes prompt whitespace and preserves content', () => {
  assert.equal(
    generationState.normalizePrompt('  blues   rock\nthrough\tthe Alps  '),
    'blues rock through the Alps',
  );
  assert.equal(generationState.normalizePrompt('   '), '');
});

test('limits prompts to the backend maximum length', () => {
  assert.equal(generationState.normalizePrompt('x'.repeat(2000)).length, 1950);
});

test('preserves existing track-count clamping behavior', () => {
  assert.equal(generationState.clampTrackCount(''), 25);
  assert.equal(generationState.clampTrackCount('3'), 5);
  assert.equal(generationState.clampTrackCount('25'), 25);
  assert.equal(generationState.clampTrackCount('150'), 100);
  assert.equal(generationState.clampTrackCount('-2'), 5);
});

test('prompt generation is ready only with non-blank text', () => {
  assert.equal(generationState.isGenerationReady('prompt', '', null), false);
  assert.equal(generationState.isGenerationReady('prompt', '   ', null), false);
  assert.equal(generationState.isGenerationReady('prompt', 'rock', null), true);
});

test('seed generation is ready only after selecting a track', () => {
  assert.equal(generationState.isGenerationReady('seed', 'ignored', null), false);
  assert.equal(
    generationState.isGenerationReady('seed', '', {video_id: 'seed-1'}),
    true,
  );
});

test('seed search is disabled when blank or already running', () => {
  assert.equal(generationState.isSeedSearchEnabled('', false), false);
  assert.equal(generationState.isSeedSearchEnabled('   ', false), false);
  assert.equal(generationState.isSeedSearchEnabled('a', false), true);
  assert.equal(generationState.isSeedSearchEnabled('artist', true), false);
});
