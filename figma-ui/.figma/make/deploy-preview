#!/usr/bin/env bash
set -euo pipefail
# Build in development mode to emit sourcemaps.
pnpm run build --mode development
figma make deploy-preview --build-dir dist
