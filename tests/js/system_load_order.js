const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

class Element {
  constructor() { this.children = []; this._text = ''; }
  set textContent(value) { this._text = value; this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  addEventListener(_event, callback) { this.click = callback; }
}
const elements = Object.fromEntries(['health', 'blender', 'gpu', 'routes', 'refresh'].map(id => [id, new Element()]));
const pending = [];
const context = {
  document: { getElementById: id => elements[id], createElement: () => new Element() },
  localStorage: { getItem: () => null },
  fetch: path => new Promise((resolve, reject) => pending.push({ path, resolve, reject })),
};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
assert.strictEqual(pending.length, 3);
elements.refresh.click();
assert.strictEqual(pending.length, 6);
const reply = (request, body) => request.resolve({ ok: true, json: async () => body });
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  // The newer load fails; an older successful response must not mask it.
  pending.slice(3).forEach(request => request.reject(new Error('offline')));
  await tick();
  const failed = ['health', 'blender', 'gpu', 'routes'].map(id => elements[id].textContent);
  assert(failed[0].includes('無法載入'));
  assert(failed[1].includes('UNAVAILABLE'));
  assert(failed[2].includes('UNAVAILABLE'));
  assert(failed[3].includes('無法載入'));
  reply(pending[0], { status: 'ok', mock: false });
  reply(pending[1], { realBlender: true, realGPU: true });
  reply(pending[2], { unclaimed: [{ methods: 'GET', path: '/old' }] });
  await tick();
  assert.deepStrictEqual(['health', 'blender', 'gpu', 'routes'].map(id => elements[id].textContent), failed);
  // A subsequent load still renders normally.
  elements.refresh.click();
  reply(pending[6], { status: 'ok', mock: false });
  reply(pending[7], { realBlender: true, realGPU: true });
  reply(pending[8], { unclaimed: [{ methods: 'GET', path: '/new' }] });
  await tick();
  assert(elements.health.textContent.includes('可連線'));
  assert(elements.gpu.textContent.includes('已偵測'));
  assert(elements.routes.textContent.includes('/new'));
})().catch(error => { console.error(error); process.exitCode = 1; });
