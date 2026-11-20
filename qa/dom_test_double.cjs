// Minimal DOM for offline state-machine tests. No CSS/layout/browser behavior.
"use strict";
function buildTestDom(html) {
  const pageControls = new Map();
  let scrollCalls = 0;
  class Element {
    constructor(tag) {
      this.tag = tag;
      this.children = [];
      this.attributes = new Map();
      this.dataset = {};
      this.style = { setProperty() {} };
      this.className = "";
      this.ownText = "";
      this.classes = new Set();
      this.classList = {
        add: (name) => this.classes.add(name),
        toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name)
      };
    }
    get textContent() { return this.ownText + this.children.map(n => n.textContent).join(""); }
    set textContent(value) { this.ownText = String(value); this.children = []; }
    get firstChild() { return this.children[0]; }
    get lastChild() { return this.children.at(-1); }
    append(...nodes) { for (const node of nodes) node.parent = this; this.children.push(...nodes); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); }
    replaceChildren(...nodes) { this.ownText = ""; this.children = nodes; }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    removeAttribute(name) { this.attributes.delete(name); delete this[name]; }
    addEventListener(name, fn) { this["on" + name] = fn; }
    querySelectorAll(tag) { return this.descendants().filter(el => el.tag === tag); }
    querySelector(tag) { return this.querySelectorAll(tag)[0]; }
    descendants() { return this.children.flatMap(el => [el, ...el.descendants()]); }
    focus() { this.focused = true; }
    scrollIntoView() { scrollCalls++; }
  }
  const document = {
    head: new Element("head"), body: new Element("body"),
    querySelector: selector => pageControls.get(selector),
    getElementById: id => pageControls.get(id),
    createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag)
  };
  const htmlBody = html.split("<script")[0];
  for (const [, tag, id] of htmlBody.matchAll(/<([a-zA-Z0-9]+)[^>]*?\sid="([^"]+)"/g)) {
    pageControls.set(id, new Element(tag));
  }
  pageControls.set(".legend", new Element("div"));
  pageControls.get("stage-counts").append(new Element("tbody"));
  return {document, pageControls, Element, get scrollCalls() { return scrollCalls; }};
}
module.exports = {buildTestDom};
