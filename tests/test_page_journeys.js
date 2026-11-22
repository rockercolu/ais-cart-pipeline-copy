'use strict';
// Exercise page handlers with a small DOM double. HTTP behavior is covered separately.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const page = fs.readFileSync('index.html', 'utf8');
const script = page.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', innerHTML: '', textContent: '', hidden: false, disabled: false, dataset: {},
    classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, removeAttribute() {}, addEventListener() {},
    querySelectorAll() { return []; }, focus() {}, scrollIntoView() {},
    insertAdjacentHTML(_pos, text) { this.innerHTML += text; },
  });
  return elements.get(id);
}
let pending, posted;
const storage = new Map();
const ctx = vm.createContext({
  document: {getElementById: element, querySelectorAll() { return []; }, querySelector: element},
  localStorage: {getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v)},
  sessionStorage: {getItem() { return null; }, setItem() {}},
  location: {search: ''}, URLSearchParams, AbortController,
  matchMedia: () => ({matches: false}), console, setInterval, clearInterval,
  fetch: async (url, options) => {
    if (url === '/api/health') return {json: async () => ({mode: 'mock'})};
    if (!options) return {json: async () => ({tools: ['Canva']})};
    posted = JSON.parse(options.body);
    return new Promise(resolve => { pending = resolve; });
  },
});
vm.runInContext(script, ctx);
const run = code => vm.runInContext(code, ctx);
(async () => {
  run('setMode("description")');
  assert.equal(element('descriptionSteps').hidden, false);
  assert.equal(element('shotSteps').hidden, true);
  element('descriptionText').value = 'Canva video subscription';
  element('descriptionText').oninput();
  assert.equal(element('goDescription').disabled, false);
  element('ownedInput').value = 'Canva';
  element('ownedForm').onsubmit({preventDefault() {}});
  assert.deepEqual(JSON.parse(storage.get('aiscart-owned-tools')), ['Canva']);
  let request = element('goDescription').onclick();
  assert.equal(posted.mode, 'description');
  assert.deepEqual(posted.ownedTools, ['Canva']);
  const before = element('result').innerHTML;
  element('descriptionText').value = 'Portable washing machine';
  element('descriptionText').oninput();
  pending({ok: true, json: async () => ({})});
  await request;
  assert.notEqual(element('result').innerHTML, before);
  assert.match(element('result').innerHTML, /Compare a purchase/);
  // Switching tabs also discards an old response and restores the buttons.
  request = element('goDescription').onclick();
  run('setMode("goal")');
  pending({ok: true, json: async () => ({})});
  await request;
  assert.match(element('result').innerHTML, /Where to start/);
  assert.equal(element('goDescription').disabled, false);
  run('resetAll()');
  assert.equal(element('descriptionText').value, '');
  assert.equal(element('goDescription').disabled, true);
  assert.deepEqual(JSON.parse(storage.get('aiscart-owned-tools')), ['Canva']);
  const api = require('../api/recommend');
  const data = await new Promise(resolve => api({method:'POST',body:{mode:'description',description:'Canva video editing subscription',shopperGoal:'make a short promo video with AI narration',ownedTools:['Canva','ElevenLabs']}},
    {setHeader(){},status(){return this;},json:resolve}));
  ctx.workflowResult = data;
  run('renderGoal(workflowResult, "make a short promo video with AI narration")');
  const rendered = element('result').innerHTML;
  assert.match(rendered, /You have \(Video editing and assembly\): Canva/);
  assert.match(rendered, /You have \(Narration and voice tracks\): ElevenLabs/);
  assert.match(rendered, /Provided narration in SongWrite and FloodHive workflows/);
  assert.match(rendered, /elevenlabs-narration/);
  console.log('PASS page entry modes, shared inventory, late-response rejection, reset preserves inventory, evidence for both owned tools');
})().catch(err => { console.error(err); process.exitCode = 1; });
