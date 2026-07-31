'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {readJson, setLoadingButton} = require('../frontend/common.js');

function response({ok = true, status = 200, body = ''} = {}) {
  return {
    ok,
    status,
    text: async () => body,
  };
}

function element() {
  const classes = new Set();
  const attributes = new Map();
  return {
    children: [],
    className: '',
    disabled: false,
    textContent: '',
    classList: {
      add: (...values) => values.forEach((value) => classes.add(value)),
      remove: (...values) => values.forEach((value) => classes.delete(value)),
      contains: (value) => classes.has(value),
    },
    setAttribute: (name, value) => attributes.set(name, String(value)),
    removeAttribute: (name) => attributes.delete(name),
    getAttribute: (name) => attributes.get(name),
    append(...values) {
      this.children.push(...values);
    },
    replaceChildren(...values) {
      this.children = values;
      this.textContent = '';
    },
  };
}

global.document = {createElement: element};

test('readJson returns parsed payloads', async () => {
  const payload = await readJson(response({body: '{"status":"ok"}'}));
  assert.deepEqual(payload, {status: 'ok'});
});

test('readJson preserves ordinary API error messages', async () => {
  await assert.rejects(
    readJson(response({ok: false, status: 400, body: '{"detail":"Invalid request"}'})),
    /Invalid request/,
  );
});

test('readJson can flatten FastAPI validation errors', async () => {
  const body = JSON.stringify({detail: [{msg: 'Field required'}, {message: 'Invalid value'}]});
  await assert.rejects(
    readJson(response({ok: false, status: 422, body}), {flattenValidationErrors: true}),
    /Field required; Invalid value/,
  );
});

test('setLoadingButton applies and restores the existing loading markup', () => {
  const button = element();
  button.textContent = 'Generate playlist';
  let startCalls = 0;
  let resetCalls = 0;

  const reset = setLoadingButton(button, {
    label: 'Generating',
    resetText: 'Generate playlist',
    ariaLabel: 'Generating playlist',
    onStart: () => { startCalls += 1; },
    onReset: () => { resetCalls += 1; },
  });

  assert.equal(button.disabled, true);
  assert.equal(button.classList.contains('is-loading'), true);
  assert.equal(button.getAttribute('aria-busy'), 'true');
  assert.equal(button.getAttribute('aria-label'), 'Generating playlist');
  assert.equal(button.children.length, 3);
  assert.equal(startCalls, 1);

  reset();
  reset();

  assert.equal(button.disabled, false);
  assert.equal(button.classList.contains('is-loading'), false);
  assert.equal(button.getAttribute('aria-busy'), undefined);
  assert.equal(button.getAttribute('aria-label'), undefined);
  assert.equal(button.textContent, 'Generate playlist');
  assert.equal(resetCalls, 1);
});
