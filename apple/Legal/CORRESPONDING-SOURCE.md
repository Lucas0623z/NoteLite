# Retrieve this build's corresponding source

Read the bundled `SOURCE-OFFER.json` for the exact full `sourceCommit`, public
source tree and `.tar.gz` archive URL. No account, fee, NDA or access token is
required to fetch that source. `main` can change; use the listed commit.
The complete public repository archive includes AudiverisCore, the linked
Apple application, native NoteWise sources, Java source counterparts, model
locks, frontend sources, build scripts and tests. The package hash inventory
is a provenance check and does not limit the corresponding-source scope.

Example, replacing SOURCE_COMMIT with that full 40-character value:

```sh
git clone https://github.com/Lucas0623z/NoteLite.git
cd NoteLite
git checkout --detach SOURCE_COMMIT
```

Alternatively download `sourceArchiveURL`, unpack it and inspect `apple/`,
`native/audio/`, `figma-ui/`, `practice-web/`, `app/src/` and the workflows.
Original license notices govern their respective files; the root MIT notice
does not override Audiveris-derived AGPL code. No restricted signing private
key or user data is part of the source offer.

## Rebuild the translated package

Use Swift 5.9 or later, with the Apple platform SDKs for Apple products:

```sh
cd apple/AudiverisCore
swift test
swift build
```

`Package.swift` is the package build recipe. Tests and fixture manifests retain
the Java input hashes used for oracle comparisons. The upstream reference and
local transformations are listed in `AUDIVERISCORE-PROVENANCE.json`.

## Rebuild the linked native application

Use an Apple Silicon Mac, Xcode 26 or newer, its iOS 26 device SDK, Python 3,
Node 22, pnpm 11.25.0 and XcodeGen 2.42.0 or later. Exact platform acceptance
commands are versioned in `.github/workflows/apple-client.yml`.

```sh
cd practice-web
npm ci
npm test
npm run build
cd ..
npm install --global pnpm@11.25.0
pnpm --dir figma-ui install --frozen-lockfile --ignore-scripts
pnpm --dir figma-ui typecheck
pnpm --dir figma-ui test
pnpm --dir figma-ui build
node apple/scripts/prepare-notewise-profiles.mjs
python3 apple/scripts/prepare-notewise-model.py
python3 apple/scripts/prepare-release-features.py --check
python3 apple/scripts/prepare-figma-ui.py
python3 apple/release/legal_resources.py prepare
cd apple
xcodegen generate --spec project.yml
xcodebuild build -project NoteLite.xcodeproj -scheme NoteLite \
  -configuration Release -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO
xcodebuild build -project NoteLite.xcodeproj -scheme NoteLiteMac \
  -configuration Release -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO
```

The standard client runs full OMR on the configured HTTPS service, while the
retained Swift image preprocessing subset is linked locally. Server and
embedded-runtime build recipes remain in the full repository. Building those
is unnecessary for the standard Apple cloud-client binary.

Device installation requires an Apple signing identity and provisioning
appropriate to that device and distribution channel. These commands do not
promise installation of a modified executable through Apple's TestFlight or
App Store. AGPL section 6 installation-information obligations, Apple's
distribution restrictions and additional rights-holder permissions require
separate review before distributing covered binaries. Public source and
license notices alone do not resolve those questions.
