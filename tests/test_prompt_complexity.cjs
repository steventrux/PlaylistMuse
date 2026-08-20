const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = {window: {}};
const script = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'prompt-complexity.js'),
  'utf8',
);
vm.runInNewContext(script, context);
const {
  analysisPayload,
  currentScore,
  debounceMs,
  filterConflicts,
  parseFilterConflict,
} = context.window.PlaylistMusePromptComplexity;

assert.equal(debounceMs, 500);
// No analysis has rendered yet (init() never ran in this DOM-less harness), so the
// score sent along with a generate request defaults to null, not a stale value.
assert.equal(currentScore(), null);

const payload = analysisPayload('  音楽を作ってください  ', {
  trackCount: 25,
  excludeLive: true,
  excludeCovers: true,
  excludeRemixes: true,
});
assert.equal(payload.prompt, '音楽を作ってください');
assert.equal(payload.track_count, 25);
assert.deepEqual(JSON.parse(JSON.stringify(payload.options)), {
  exclude_live: true,
  exclude_covers: true,
  exclude_remixes: true,
});

const marker = 'FILTER_CONFLICT::exclude_live::The request requires live recordings.';
assert.deepEqual(
  JSON.parse(JSON.stringify(parseFilterConflict(marker))),
  {
    option: 'exclude_live',
    message: 'The request requires live recordings.',
  },
);
assert.deepEqual(
  JSON.parse(JSON.stringify(filterConflicts({issues: ['other issue', marker]}))),
  [{
    option: 'exclude_live',
    message: 'The request requires live recordings.',
  }],
);
