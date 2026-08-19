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
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

function makeContext(elements, timers) {
  let nextTimerId = 1;
  const fetchQueue = [];
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
      const entry = deferred();
      fetchQueue.push({url, opts, entry});
      return entry.promise;
    },
  };
  return {context, fetchQueue};
}

function fireOnlyTimer(timers) {
  const [[id, fn]] = timers.entries();
  timers.delete(id);
  fn();
}

test('a failed re-analysis of the current prompt keeps the last good score instead of blanking it', async () => {
  const elements = new Map();
  const ids = [
    'prompt', 'prompt-complexity', 'prompt-complexity-trigger', 'prompt-complexity-popover',
    'prompt-complexity-score', 'prompt-complexity-summary', 'prompt-complexity-performance',
    'prompt-clarity',
  ];
  ids.forEach((id) => elements.set(id, makeElement()));

  const timers = new Map();
  const {context, fetchQueue} = makeContext(elements, timers);

  const script = fs.readFileSync(
    path.join(__dirname, '..', 'frontend', 'prompt-complexity.js'),
    'utf8',
  );
  vm.runInNewContext(script, context);

  const api = context.window.PlaylistMusePromptComplexity;
  const promptEl = elements.get('prompt');
  const inputHandler = promptEl.__listeners.input[0];

  // First prompt: debounce fires, request succeeds, a real score is rendered.
  promptEl.value = 'dance-pop playlist with a happy feel';
  inputHandler();
  fireOnlyTimer(timers);
  assert.equal(fetchQueue.length, 1);
  const firstEnsured = api.ensureCurrentAnalysis();
  fetchQueue[0].entry.resolve({
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
  await firstEnsured;
  assert.equal(api.currentScore(), 42, 'first successful analysis should render its score');

  // User edits the prompt further; the re-analysis for the new text fails
  // (timeout, rate limit, transient provider error -- exactly what the
  // gemini rate-limit skips in production logs looked like).
  promptEl.value = 'dance-pop playlist with a happy feel and a driving 90s techno bassline';
  inputHandler();
  fireOnlyTimer(timers);
  assert.equal(fetchQueue.length, 2, 'editing the prompt should trigger a fresh analysis request');
  const secondEnsured = api.ensureCurrentAnalysis();
  fetchQueue[1].entry.resolve({ok: false, status: 502});
  await secondEnsured;

  assert.equal(
    api.currentScore(),
    42,
    'a failed re-analysis for the prompt currently on screen must not erase the last good score',
  );
});

test('a failed analysis still clears the score once the prompt has moved on from the failed request', async () => {
  const elements = new Map();
  const ids = [
    'prompt', 'prompt-complexity', 'prompt-complexity-trigger', 'prompt-complexity-popover',
    'prompt-complexity-score', 'prompt-complexity-summary', 'prompt-complexity-performance',
    'prompt-clarity',
  ];
  ids.forEach((id) => elements.set(id, makeElement()));

  const timers = new Map();
  const {context, fetchQueue} = makeContext(elements, timers);

  const script = fs.readFileSync(
    path.join(__dirname, '..', 'frontend', 'prompt-complexity.js'),
    'utf8',
  );
  vm.runInNewContext(script, context);

  const api = context.window.PlaylistMusePromptComplexity;
  const promptEl = elements.get('prompt');
  const inputHandler = promptEl.__listeners.input[0];

  promptEl.value = 'dance-pop playlist with a happy feel';
  inputHandler();
  fireOnlyTimer(timers);
  const firstEnsured = api.ensureCurrentAnalysis();
  fetchQueue[0].entry.resolve({
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
  await firstEnsured;
  assert.equal(api.currentScore(), 42);

  promptEl.value = 'dance-pop playlist with a happy feel and a driving 90s techno bassline';
  inputHandler();
  fireOnlyTimer(timers);
  assert.equal(fetchQueue.length, 2);
  // Grab a handle on the in-flight analyze() promise while the prompt still
  // matches the request that's in flight for it.
  const secondEnsured = api.ensureCurrentAnalysis();

  // Before that request resolves, the user clears the box entirely.
  promptEl.value = '';
  inputHandler();

  fetchQueue[1].entry.resolve({ok: false, status: 502});
  await secondEnsured;

  assert.equal(
    api.currentScore(),
    null,
    'once the prompt has moved past the failed request, a stale score must not linger',
  );
});
