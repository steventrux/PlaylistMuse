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
const {analyze, quantityPoints} = context.window.PlaylistMusePromptComplexity;

assert.equal(quantityPoints(15), 0);
assert.equal(quantityPoints(25), 3);
assert.equal(quantityPoints(50), 7);
assert.equal(quantityPoints(100), 11);

const simple = analyze('Rock anni 70 per un viaggio', {trackCount: 15});
assert.equal(simple.level, 'Simple');
assert.ok(simple.score >= 10 && simple.score < 20);

const complex = analyze(
  'Crea una playlist rock e blues dal 1968 al 1982, senza live, alternando brani famosi e meno conosciuti, con energia crescente',
  {trackCount: 50},
);
assert.equal(complex.level, 'Complex');
assert.equal(complex.hardConstraints, 1);
assert.equal(complex.structures, 2);
assert.ok(complex.score >= 40 && complex.score < 65);

const filtered = analyze('Rock anni 70', {
  trackCount: 25,
  excludeLive: true,
  excludeCovers: true,
  excludeRemixes: true,
});
assert.equal(filtered.hardConstraints, 3);
assert.ok(filtered.score > simple.score);

assert.equal(analyze(''), null);
