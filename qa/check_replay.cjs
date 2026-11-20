// Runs the packaged replay's own script against a minimal DOM test double.
// Tests state transitions and event handlers only. No browser, layout or timing fidelity.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const file = process.argv[2];
const deepLink = process.argv[3];
if (!file) throw new Error("Usage: node qa/check_replay.cjs examples/preview/replay.html");
const html = fs.readFileSync(file, "utf8");
const scripts = Array.from(html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g));
const data = scripts.find(([_, attrs]) => attrs.includes('id="source"'))[2];
const code = scripts.find(([_, attrs]) => !attrs.trim())[2];
const record = JSON.parse(data).record;
const {buildTestDom} = require("./dom_test_double.cjs");
const dom = buildTestDom(html);
const {document, pageControls, Element} = dom;
const node = id => pageControls.get(id);
pageControls.set("source", new Element("script"));
node("source").textContent = data;
let activeTimer;
vm.runInNewContext(code, {
  document, location: {hash:deepLink ? "#check="+encodeURIComponent(deepLink) : ""},
  window: {addEventListener() {}}, matchMedia: () => ({matches: true}),
  requestAnimationFrame() {},  // Deliberately skip geometric layout.
  setInterval(fn) { activeTimer = fn; return 1; },
  clearInterval() { activeTimer = undefined; }
}, {filename: "packaged-replay.js", timeout: 3000});

const cards = node("board").descendants().filter(el => el.dataset.check);
assert.equal(cards.length, record.input.checks.length);
if (deepLink) {
  assert.equal(node("seek").value, String(record.events.length));
  const selected = cards.find(c => c.attributes.get("aria-pressed") === "true");
  assert.equal(selected.dataset.check, deepLink);
  assert.ok(node("details").textContent.includes(deepLink));
}
assert.equal(node("reduce").checked, true);
assert.equal(document.body.classes.has("motion"), false);
const requiredEdges = record.input.checks.reduce((total, c) => total + (c.depends_on || []).length, 0);
const arrows = node("board").descendants().filter(el => el.attributes.has("marker-end"));
assert.equal(arrows.length, requiredEdges);

function seek(position) {
  node("seek").value = String(position);
  node("seek").oninput();
}
const actualChecks = Object.fromEntries(cards.map(el => [el.dataset.check, el]));
const observed = Object.fromEntries(cards.map(el => [el.dataset.check, "queued"]));
let maxActive = 0;
let parallelCursor = 0;
let preMergeFailed = false;
for (let i = 0; i <= record.events.length; i++) {
  if (i) {
    const e = record.events[i - 1];
    observed[e.check_id] = e.state;
  }
  seek(i);
  const active = cards.filter(c => c.dataset.state === "running").length;
  if (active > maxActive) { maxActive = active; parallelCursor = i; }
  assert.equal(node("active-count").textContent, "실행 중 " + active);
  assert.equal(node("current").disabled, active === 0);
  for (const [id, state] of Object.entries(observed)) assert.equal(actualChecks[id].dataset.state, state);
  if (i < record.events.length) {
    assert.equal(node("defect-total").textContent, "—");
    const failed = cards.find(c => c.dataset.state === "failed");
    if (failed) {
      failed.onclick();
      assert.match(node("details").textContent, /최종 분석 보기/);
      assert.doesNotMatch(node("details").textContent, /확인된 원인/);
      preMergeFailed = true;
    }
  }
}
assert.equal(dom.scrollCalls, 0);
for (const row of node("stage-counts").querySelectorAll("tr")) {
  for (const cell of row.querySelectorAll("td")) {
    const expected = record.input.checks.filter(c => c.stage === row.dataset.stage &&
      observed[c.id] === cell.dataset.status).length;
    assert.equal(cell.textContent, String(expected));
  }
}
assert.equal(node("defect-total").textContent, String(new Set(record.defects.map(d => d.fingerprint)).size));
for (const d of record.defects) {
  actualChecks[d.check_ids[0]].onclick();
  const text = node("details").textContent;
  for (const marker of ["깨진 목표·기준", "로그·캡처", "가설", "확인된 원인", d.minimal_fix, d.next_regression])
    assert.ok(text.includes(marker), "missing failure detail " + marker);
}
assert.equal(node("end").disabled, true);
node("step-back").onclick();
node("step-next").onclick();
assert.equal(node("seek").value, String(record.events.length));
if (maxActive) {
  seek(parallelCursor);
  node("current").onclick();
  assert.equal(dom.scrollCalls, 1);
  node("reduce").checked = false;
  node("reduce").onchange();
  assert.ok(document.body.classes.has("motion"));
  node("play").onclick();
  assert.ok(document.body.classes.has("playing"));
  activeTimer();
  assert.equal(node("seek").value, String(parallelCursor + 1));
  node("end").onclick();
  assert.equal(document.body.classes.has("playing"), false);
}
console.log(JSON.stringify({renderer:"Node DOM test double", cursors:record.events.length+1,
  cards:cards.length, dependencyEdges:arrows.length, peakParallel:maxActive,
  preMergeFailedChecked:preMergeFailed, automaticScrolls:0, passed:true}));
