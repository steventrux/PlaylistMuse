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
const {analysisPayload, debounceMs} = context.window.PlaylistMusePromptComplexity;

assert.equal(debounceMs, 500);

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
