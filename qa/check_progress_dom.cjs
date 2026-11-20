// Exercise the shipped progress script with deterministic local journal snapshots.
// This is a DOM test double; no pixels, CSS animation frames, or real browser are observed.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {buildTestDom} = require("./dom_test_double.cjs");
const [pagePath, recordPath] = process.argv.slice(2);
if (!pagePath || !recordPath) throw new Error("Usage: node qa/check_progress_dom.cjs views/progress.html RECORD");
const html = fs.readFileSync(pagePath, "utf8");
const record = JSON.parse(fs.readFileSync(recordPath, "utf8"));
const dom = buildTestDom(html);
const {document} = dom;
const q = id => document.getElementById(id);
const window = {addEventListener() {}};
let now = Date.parse(record.created_at);
class MockClock extends Date { static now() { return now; } }
const timers = new Map();
const media = {matches: true, addEventListener() {}};
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInNewContext(code, {document, window, Date:MockClock, matchMedia: () => media,
  requestAnimationFrame() {}, setInterval(fn, ms) {timers.set(ms,fn);}}, {timeout:3000});
const poll = document.head.firstChild;
assert.match(poll.src, /^\.\/progress\.index\.js\?read=/);
poll.onerror();
assert.match(q("phase").textContent, /연결 대기/);
const info = {
  phase:"waiting", run_id:null, round:null, attempt:null, product:"", revision:"",
  created_at:null, last_event_at:null, seq:0, checks:[], states:{}, decision:null,
  defects:null, observed_at:new Date(now).toISOString(), watching:true, stopped:false, heartbeat_ms:4500
};
window.ITR_PROGRESS({...info});
assert.equal(q("current").disabled, true);
assert.equal(q("defect-total").textContent, "—");
const getCards = () => q("board").descendants().filter(c => c.dataset.check);
const checks = record.input.checks.map(c => Object.fromEntries(
  ["id","title","role","stage","method","depends_on"].map(k => [k,c[k]])));
const states = {};
let peak = 0, parallelState;
for (const e of record.events) {
  states[e.check_id] = e.state;
  const n = Object.values(states).filter(s => s === "running").length;
  if (n > peak) {peak = n; parallelState = {...states};}
}
assert.ok(peak >= 2, "fixture must exercise concurrent work");
const live = {...info, phase:"live", run_id:record.run_id, round:record.round,
  attempt:record.attempt, checks, states:parallelState, seq:1,
  last_event_at:record.created_at, revision:record.input.revision, product:record.input.product};
window.ITR_PROGRESS(live);
assert.equal(getCards().length, checks.length);
assert.equal(getCards().filter(e => e.dataset.state === "running").length, peak);
assert.equal(q("active").textContent, "실행 확인 "+peak+"건");
assert.match(q("clock").textContent, /KST$/);
assert.equal(q("current").disabled, false);
assert.equal(q("reduce").checked, true);
assert.equal(document.body.classes.has("motion"), false);
q("reduce").checked = false;
q("reduce").onchange();
assert.ok(document.body.classes.has("motion"));
const animationRules = Array.from(html.matchAll(/([^{}]+)\{[^{}]*animation:\s*(pulse|trace)\b[^{}]*\}/g));
assert.equal(animationRules.length,2);
for (const selector of animationRules) {
  assert.ok(selector[1].includes(".motion .card[data-state=running]"), "motion selector outside active cards");
}
assert.ok(html.includes("animation:pulse") && html.includes("animation:trace"));
assert.equal(dom.scrollCalls, 0);
q("current").onclick();
assert.equal(dom.scrollCalls, 1);
const scrollBeforeUpdates = dom.scrollCalls;
for (const state of [
  {...live,phase:"interrupted"}, {...live,phase:"unconfirmed"}, {...live,phase:"invalid"},
  {...live,phase:"synchronizing"}, {...live,watching:false}, {...live,stopped:true}
]) {
  window.ITR_PROGRESS(state);
  assert.equal(getCards().filter(e => e.dataset.state === "running").length, 0);
  assert.equal(q("current").disabled, true);
  assert.equal(q("defect-total").textContent, "—");
  assert.equal(q("report").hidden, true);
}
window.ITR_PROGRESS(live);
now += live.heartbeat_ms + 1;
timers.get(1100)();
assert.equal(getCards().filter(e => e.dataset.state === "running").length, 0);
assert.equal(document.body.classes.has("motion"), false);
assert.match(q("phase").textContent,/연결 확인/);
now -= live.heartbeat_ms + 1;
window.ITR_PROGRESS(live);
timers.get(360)();
document.head.firstChild.onerror();
assert.equal(q("current").disabled, true);
assert.equal(document.body.classes.has("motion"), false);
const final = {...live,phase:"sealed",seq:record.events.length,states,
  defects:new Set(record.defects.map(d => d.fingerprint)).size,decision:record.decision.status};
window.ITR_PROGRESS({...final, report:"data:invalid"});
assert.equal(q("report").hidden, true);
const reportPath = "reports/round-" + String(record.round).padStart(4,"0") +
  "-attempt-" + String(record.attempt).padStart(4,"0") + "/replay.html";
window.ITR_PROGRESS({...final,report:reportPath});
assert.equal(q("report").hidden, false);
assert.equal(q("report").href.split("#")[0], reportPath);
assert.equal(q("defect-total").textContent,String(final.defects));
const failed = getCards().find(e => e.dataset.state === "failed");
assert.ok(failed);
failed.onclick();
assert.equal(q("report").href,reportPath+"#check="+encodeURIComponent(failed.dataset.check));
assert.ok(q("details").textContent.includes(failed.dataset.check));
assert.ok(q("details").textContent.includes("실패"));
for (const row of q("stage-counts").querySelectorAll("tr"))
  for (const cell of row.querySelectorAll("td")) {
    const expected = checks.filter(c => c.stage === row.dataset.stage &&
      states[c.id] === cell.dataset.status).length;
    assert.equal(cell.textContent, String(expected));
  }
assert.equal(dom.scrollCalls, scrollBeforeUpdates);
console.log(JSON.stringify({renderer:"Node DOM test double",observedSnapshots:["waiting","live","interrupted",
  "unconfirmed","invalid","synchronizing","once","stopped","stale-heartbeat","index-error","sealed"],
  cards:getCards().length,parallelCards:peak,explicitScrolls:dom.scrollCalls,
  unsolicitedScrolls:0,sealedReportLink:reportPath,cssSelectorsInspected:true,pixelsMeasured:false,passed:true}));
