import test from "node:test";
import assert from "node:assert/strict";
import { createScoreRenderHost, resolveOSMDConstructor } from "../src/app/osmd.ts";

test("OSMD resolves Vite 8's UMD default export used by the actual browser prebundle", () => {
  class Constructor {}
  assert.equal(resolveOSMDConstructor({ default: { OpenSheetMusicDisplay: Constructor } }), Constructor);
});
test("OSMD also accepts an explicit named export", () => {
  class Constructor {}
  assert.equal(resolveOSMDConstructor({ OpenSheetMusicDisplay: Constructor }), Constructor);
});
test("an invalid OSMD module fails explicitly instead of reporting a rendered score", () => {
  for (const module of [null, {}, { default: {} }, { OpenSheetMusicDisplay: "invalid" }]) assert.throws(() => resolveOSMDConstructor(module), /未能加载/);
});

class Element {
  parentElement: Element | null = null;
  children: Element[] = [];
  id = "";
  content = "";
  ownerDocument = { createElement: () => new Element() };
  appendChild(child: Element) { child.remove(); child.parentElement = this; this.children.push(child); return child; }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    this.parentElement = null;
  }
  pages(): Element[] { return this.children.flatMap((child) => child.id === "osmdSvgPage1" ? [child] : child.pages()); }
}

function fixture() {
  const container = new Element();
  const createHost = () => createScoreRenderHost(container as unknown as HTMLElement);
  return { container, createHost };
}

class Display {
  host: Element;
  clears = 0;
  clearedWhileVisible = false;
  constructor(host: HTMLElement) { this.host = host as unknown as Element; }
  render(content: string) {
    const canvas = new Element(); canvas.id = "osmdCanvasPage1";
    const page = new Element(); page.id = "osmdSvgPage1"; page.content = content;
    canvas.appendChild(page); this.host.appendChild(canvas);
  }
  clear() {
    this.clears++;
    this.clearedWhileVisible ||= this.host.parentElement !== null;
    // Match the failure boundary: drawing clears while the page wrapper remains.
    for (const page of this.host.pages()) page.content = "";
  }
}

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

test("replacing a rendered score detaches its empty Page1 wrappers before clearing and preserves the new score", () => {
  const { container, createHost } = fixture();
  const previous = createHost(); const oldDisplay = new Display(previous.element); previous.attach(oldDisplay);
  oldDisplay.render("D5 · revision 2");
  previous.dispose();
  assert.equal(oldDisplay.clearedWhileVisible, false);
  assert.equal(container.pages().length, 0);
  const current = createHost(); const newDisplay = new Display(current.element); current.attach(newDisplay);
  newDisplay.render("D6 · revision 3");
  previous.dispose();
  assert.deepEqual(container.pages().map((page) => page.content), ["D6 · revision 3"]);
  assert.equal(container.children.length, 1);
  assert.equal(newDisplay.clears, 0);
});

test("an old load that appends Page1 after cleanup finishes only in its detached host", async () => {
  const { container, createHost } = fixture();
  const oldHost = createHost(); const oldDisplay = new Display(oldHost.element); oldHost.attach(oldDisplay);
  const load = deferred();
  const pending = load.promise.then(() => {
    oldDisplay.render("late revision 2");
    if (!oldHost.isActive()) oldHost.dispose();
  });
  oldHost.dispose();
  const latest = createHost(); const latestDisplay = new Display(latest.element); latest.attach(latestDisplay);
  latestDisplay.render("D6 · revision 3");
  load.resolve(); await pending;
  assert.equal(oldDisplay.clears, 2);
  assert.equal(oldDisplay.clearedWhileVisible, false);
  assert.deepEqual(container.pages().map((page) => page.content), ["D6 · revision 3"]);
  assert.equal(container.children.length, 1);
  assert.equal(latestDisplay.clears, 0);
});

test("rapid zoom and save renders resolving out of order leave one current Page1 even when an old load rejects", async () => {
  const { container, createHost } = fixture();
  const renders = ["zoom 100%", "zoom 110%", "D6 · revision 3"].map((label) => {
    const host = createHost(); const display = new Display(host.element); host.attach(display);
    const load = deferred();
    const pending = load.promise.then(() => {
      display.render(label);
      if (!host.isActive()) host.dispose();
    }, () => host.dispose());
    return { host, display, load, pending };
  });
  renders[0].host.dispose(); renders[1].host.dispose();
  renders[2].load.resolve(); await renders[2].pending;
  renders[1].load.reject(new Error("old load failed")); await renders[1].pending;
  renders[0].load.resolve(); await renders[0].pending;
  assert.deepEqual(container.pages().map((page) => page.content), ["D6 · revision 3"]);
  assert.equal(container.children.length, 1);
  assert.equal(renders[2].display.clears, 0);
});

test("a display attached after its owner was disposed is cleared while detached and cannot alter another owner", () => {
  const { container, createHost } = fixture();
  const oldHost = createHost(); oldHost.dispose();
  const current = createHost(); const currentDisplay = new Display(current.element); current.attach(currentDisplay);
  currentDisplay.render("current score");
  const lateDisplay = new Display(oldHost.element); lateDisplay.render("late constructor"); oldHost.attach(lateDisplay);
  assert.equal(lateDisplay.clears, 1);
  assert.equal(lateDisplay.clearedWhileVisible, false);
  assert.deepEqual(container.pages().map((page) => page.content), ["current score"]);
});
