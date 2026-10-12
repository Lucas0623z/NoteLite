{
  // Files whose changes trigger the install script + dev server restart.
  // Glob syntax: doublestar (supports **, *, ?, [abc], {a,b}). Paths are
  // repo-relative and case-sensitive. `.mise.toml` and the scripts under
  // `.figma/make/` are always watched regardless of these lists.
  //
  // Each key accepts a shorthand array of globs:
  //   "installOn": ["package.json"]
  // or an object with includes/excludes:
  //   "installOn": { "includes": ["**/*.json"], "excludes": ["test/**"] }
  //
  // Only list files that affect the *toolchain or dependency tree* here —
  // NOT application source files. Vite's dev server already watches
  // application code (src/**/*) and config (vite.config.ts) via its own HMR
  // pipeline, so including them here would cause a redundant full restart.
  "installOn": [
    "package.json",
    "pnpm-lock.yaml"
  ],
  // Files whose changes trigger only a dev server restart (no install).
  "restartOn": []
}
