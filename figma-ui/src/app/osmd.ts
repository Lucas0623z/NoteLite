import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";

/** OSMD's npm bundle is UMD. Vite 8 can expose its exports under `default`. */
export function resolveOSMDConstructor(module: unknown): typeof OpenSheetMusicDisplay {
  const loaded = module as { OpenSheetMusicDisplay?: unknown; default?: { OpenSheetMusicDisplay?: unknown } } | null;
  const constructor = loaded?.OpenSheetMusicDisplay ?? loaded?.default?.OpenSheetMusicDisplay;
  if (typeof constructor !== "function") throw new Error("乐谱排版组件未能加载，请重新打开页面。");
  return constructor as typeof OpenSheetMusicDisplay;
}
