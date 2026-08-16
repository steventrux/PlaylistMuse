const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = {window: {}};
const script = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'prompt-surprise.js'),
  'utf8',
);
vm.runInNewContext(script, context);
const {buildPrompt, MUSIC_FAMILIES, pickFamily} = context.window.PlaylistMusePromptSurprise;

// The same music family must not come up again within a short window of
// consecutive picks -- this is the fix for "Surprise me keeps suggesting the
// same combinations" (small pool of 14 families, no repeat-avoidance before).
const WINDOW = 4;
const recent = [];
for (let i = 0; i < 80; i += 1) {
  const family = pickFamily();
  assert.ok(
    !recent.includes(family),
    `family repeated within the last ${WINDOW} picks at iteration ${i}`,
  );
  recent.push(family);
  if (recent.length > WINDOW) recent.shift();
}

// Every family must still be reachable (the exclusion window shouldn't strand
// any of them permanently).
const seen = new Set();
for (let i = 0; i < 200 && seen.size < MUSIC_FAMILIES.length; i += 1) {
  seen.add(pickFamily());
}
assert.equal(seen.size, MUSIC_FAMILIES.length);

function wordCount(value) {
  return String(value).trim().split(/\s+/).filter(Boolean).length;
}

for (let i = 0; i < 30; i += 1) {
  const surprise = buildPrompt('surprise');
  const words = wordCount(surprise);
  assert.ok(words >= 18 && words <= 36, `surprise prompt out of range (${words} words): ${surprise}`);

  const example = buildPrompt('example');
  const exampleWords = wordCount(example);
  assert.ok(
    exampleWords >= 10 && exampleWords <= 20,
    `example prompt out of range (${exampleWords} words): ${example}`,
  );
}
