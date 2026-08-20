const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function makeElement() {
  const classSet = new Set();
  const listeners = {};
  return {
    value: '',
    textContent: '',
    title: '',
    hidden: false,
    dataset: {},
    style: {setProperty() {}},
    classList: {
      add: (...names) => names.forEach((name) => classSet.add(name)),
      remove: (...names) => names.forEach((name) => classSet.delete(name)),
      toggle(name, force) {
        const on = force === undefined ? !classSet.has(name) : Boolean(force);
        if (on) classSet.add(name); else classSet.delete(name);
        return on;
      },
      contains: (name) => classSet.has(name),
    },
    setAttribute() {},
    getAttribute() { return null; },
    addEventListener(type, handler) {
      (listeners[type] ||= []).push(handler);
    },
    removeEventListener() {},
    closest() { return null; },
    insertAdjacentElement() {},
    replaceChildren() {},
    setSelectionRange() {},
    focus() {},
    __listeners: listeners,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((res) => { resolve = res; });
  return {promise, resolve};
}

test('ensureCurrentAnalysis awaits an in-flight analyze() instead of abandoning it', async () => {
  const elements = new Map();
  const ids = [
    'prompt', 'prompt-complexity', 'prompt-complexity-trigger', 'prompt-complexity-popover',
    'prompt-complexity-score', 'prompt-complexity-summary', 'prompt-complexity-performance',
    'prompt-clarity',
  ];
  ids.forEach((id) => elements.set(id, makeElement()));

  const timers = new Map();
  let nextTimerId = 1;
  const fetchCalls = [];
  const fetchDeferred = deferred();

  const context = {
    document: {
      getElementById: (id) => elements.get(id),
      createElement: () => makeElement(),
      addEventListener() {},
    },
    window: {
      setTimeout: (fn) => {
        const id = nextTimerId++;
        timers.set(id, fn);
        return id;
      },
      clearTimeout: (id) => timers.delete(id),
    },
    AbortController,
    fetch: (url, opts) => {
      fetchCalls.push({url, opts});
      return fetchDeferred.promise;
    },
  };

  const script = fs.readFileSync(
    path.join(__dirname, '..', 'frontend', 'prompt-complexity.js'),
    'utf8',
  );
  vm.runInNewContext(script, context);

  const promptEl = elements.get('prompt');
  promptEl.value = 'dance-pop playlist with a happy feel';

  // Simulate typing: the debounce timer is armed but not yet fired.
  const inputHandler = promptEl.__listeners.input[0];
  assert.equal(typeof inputHandler, 'function');
  inputHandler();
  assert.equal(timers.size, 1, 'debounce timer should be armed after typing');

  // Simulate the 500ms debounce elapsing: analyze() starts and calls fetch(),
  // which is still pending -- exactly the state generate() races against.
  const [timerCallback] = timers.values();
  timerCallback();
  assert.equal(fetchCalls.length, 1, 'analyze() should have started exactly one request');

  const api = context.window.PlaylistMusePromptComplexity;
  assert.equal(api.currentScore(), null, 'no analysis has resolved yet');

  // This is what prompt-validation-guard.js calls right before letting a
  // Generate click through -- it must not resolve until the in-flight
  // analysis actually completes.
  const ensuredPromise = api.ensureCurrentAnalysis();

  let settled = false;
  ensuredPromise.then(() => { settled = true; });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(settled, false, 'ensureCurrentAnalysis must not resolve before the pending fetch does');
  assert.equal(fetchCalls.length, 1, 'ensureCurrentAnalysis must not fire a duplicate request');

  fetchDeferred.resolve({
    ok: true,
    json: async () => ({
      score: 42,
      level: 'Moderate',
      dimensions: 2,
      hard_constraints: 1,
      soft_constraints: 1,
      structures: 0,
      issues: [],
      performance_notes: [],
    }),
  });

  const result = await ensuredPromise;
  assert.ok(result, 'ensureCurrentAnalysis should resolve with the completed analysis');
  assert.equal(result.score, 42);
  assert.equal(api.currentScore(), 42, 'complexity_score sent with the generate request must reflect the completed analysis');
});
