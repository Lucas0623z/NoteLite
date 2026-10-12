import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";

/** OSMD's npm bundle is UMD. Vite 8 can expose its exports under `default`. */
export function resolveOSMDConstructor(module: unknown): typeof OpenSheetMusicDisplay {
  const loaded = module as { OpenSheetMusicDisplay?: unknown; default?: { OpenSheetMusicDisplay?: unknown } } | null;
  const constructor = loaded?.OpenSheetMusicDisplay ?? loaded?.default?.OpenSheetMusicDisplay;
  if (typeof constructor !== "function") throw new Error("乐谱排版组件未能加载，请重新打开页面。");
  return constructor as typeof OpenSheetMusicDisplay;
}

/** Each async render owns a disposable child, never the React/shared container. */
export function createScoreRenderHost(container: HTMLElement) {
  const element = container.ownerDocument.createElement("div");
  container.appendChild(element);
  let active = true;
  let display: { clear(): void } | undefined;
  const dispose = () => {
    active = false;
    // OSMD.clear() can retain empty canvas/SVG wrappers. Detach before clearing,
    // including when an in-flight load finishes after the first cleanup.
    element.remove();
    display?.clear();
  };
  return {
    element,
    isActive: () => active,
    attach(instance: { clear(): void }) {
      display = instance;
      if (!active) dispose();
    },
    dispose,
  };
}
