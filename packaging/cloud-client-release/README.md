# Cloud-client release packaging

This gate is for the Figma cloud client. The server keeps Audiveris, OMR jobs,
score editing, MusicXML/MIDI conversion and account administrator credentials.
The client keeps its UI resources and platform code. This gate never deploys,
reads signing keys, changes the Figma UI, or requires a network connection for
local practice. The existing embedded-Audiveris and Java desktop distribution
workflows are separate legacy products and are not this cloud-client release.

ZIP, IPA, JS and native binaries can be inspected or reverse engineered.
Minification removes source-level conveniences; it does not encrypt the UI or
make it impossible to unpack. Signing identifies the publisher and detects
changes to signed code/resources. Windows Authenticode does not seal arbitrary
JS resources in a portable ZIP. SHA256 inventory checks are build integrity
checks, not a replacement for a signed installer or runtime trust enforcement.

## Prepare and verify resources

First build `figma-ui` and `practice-web` with their production build scripts.
From the repository root, choose a new output directory:

```powershell
python packaging/cloud-client-release/release.py prepare --output work/client-resource-candidate
python packaging/cloud-client-release/release.py verify --input work/client-resource-candidate
python packaging/cloud-client-release/release.py package --input work/client-resource-candidate --platform web-candidate --output work/client-resource-candidate.zip
python -B packaging/cloud-client-release/test_release.py
```

The generated resource ZIP is a review/build input, not an installable native
app. Its manifest and report explicitly say `readyForDistribution: false`.
The independent `cloud-client-release-gate.yml` CI workflow runs these content
checks and the actual unsigned Windows rejection test, then retains the ZIP
under `unsigned-cloud-client-resources`. It does not sign, deploy or mark a
native app ready. Release certificates and notarization remain separate.
Figma assets are copied byte-for-byte, so ratios and layouts are preserved.
Sourcemap files are omitted. Inline/external sourcemap references, dev/test
markers, source/server OMR code, opaque nested archives, private-key/database
paths, credential-shaped literals, user recordings and uploaded scores stop
the gate. Nothing is printed from a suspected credential. Only the repository's
explicit `demo.musicxml` sample is accepted as a bundled score.

The original app license, practice `THIRD-PARTY.txt`, font notices and the full
installed Figma runtime dependency licenses are retained. Product UI branding
uses NoteLite/NoteWise; the original upstream names, copyrights and notices
remain in license files. Any required corresponding source offer remains a
separate free source archive; this gate does not remove or restrict it.

## Native distribution gate

Integrate the prepared resources into the native app **before** signing.
Use a Release build without DEBUG, diagnostics, test fixtures, .map/.pdb/.dSYM
or private configuration. Keep debug symbols separately for crash analysis.
The final app must include the license/notices. This format accepts a complete
ordinary directory and rejects symlinks/junctions; repackage framework layouts
using the platform's native signed installer tooling when links are required.

```text
python packaging/cloud-client-release/release.py package --input /path/NoteLite.app --platform ios --publisher TEAMID1234 --output /path/NoteLite.ipa
python packaging/cloud-client-release/release.py package --input /path/NoteLite.app --platform macos --publisher TEAMID1234 --output /path/NoteLite-mac.zip
python packaging/cloud-client-release/release.py package --input C:/release/NoteLite --platform windows --publisher "CN=Your actual publisher subject" --output C:/release/NoteLite-windows.zip
```

Apple checks run on macOS: strict/deep codesign verification, expected Team ID,
no development entitlement, and a real native executable. iOS additionally
requires a current exact-App-ID App Store profile, not a simulator/Ad Hoc build.
The IPA is assembled as `Payload/<app>.app`. macOS additionally requires hardened
runtime and acceptance by `spctl` (notarize/staple the app before this gate).
App Store Connect upload validation and actual device acceptance remain
separate required release work; this script does not perform either.

Windows checks run on Windows: every bundled EXE/DLL/MSI needs a valid timestamped
Authenticode signature from the configured publisher. Obtain the signing
certificate and timestamp these files in the trusted signing environment;
never put certificate/private-key material in the package or repository. An
unsigned app or a resources-only folder cannot produce a native release ZIP.
Publish a signed installer for Windows to authenticate the full installation
payload; this portable ZIP is not an authenticated installer.

After packaging, the script reads the real archive and verifies every entry
against the pre-signing payload bytes, then writes its SHA256 report. It never
claims that offline operation is licensed by a server, that unpacking is
prevented, or that a resource-only inspection proves native release signing.
