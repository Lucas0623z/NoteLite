# 黑白键AI cloud-client iOS release

Use `Apple cloud client signed release` (`apple-cloud-release.yml`) with a manual
workflow dispatch on the current application branch. The registered app remains
`com.lucas0623z.yinban`, team `G74YSFJX76`; the displayed brand is
`黑白键AI-你的陪练搭子`. This workflow uses the standard `apple/project.yml`
client, production Figma resources and local NoteWise DSP/CoreML model. OMR runs
on the configured HTTPS server; no embedded Audiveris/JDK artifact is downloaded
or included in this client.

Supply the successful `Apple clients` run ID for the exact release commit. The
gate checks GitHub workflow, SHA and current-attempt native jobs, verifies each
artifact's GitHub SHA256, and reads the real Xcode test results. Core persistence,
new interactions, iPhone/iPad direction restoration, both macOS window sizes,
local DSP/MIDI and actual shipped CoreML inference/silence tests must pass.
Skipped tests, a green parent suite, screenshots alone or another source SHA do
not qualify. macOS evidence explicitly uses a native virtual test display.

`verify` creates an unsigned device archive. `export` uses the existing
`IOS_DISTRIBUTION_P12_BASE64`, `IOS_DISTRIBUTION_P12_PASSWORD` and
`IOS_APP_STORE_PROFILE_BASE64` secrets in an ephemeral keychain. Both the archived
app and actual exported IPA are checked for device platform, bundle/version,
resource byte hashes, model notices, absence of embedded OMR/test/private data,
and (for export) actual signature, team, entitlements, profile and certificate.
Keys, keychain, profile, private build directory and captured tool output are
removed instead of uploaded as artifacts. The public report and package hash are
retained with the actual verified package.

`upload` defaults to `false`. Explicit `export` plus `upload=true` uses the
existing `ASC_API_KEY_ID`, `ASC_API_ISSUER_ID` and `ASC_API_PRIVATE_KEY_BASE64`
secrets to validate and upload only the verified IPA to App Store Connect for
TestFlight processing. It never submits an App Store review or public release,
enables external testers or claims Apple's processing has completed. Check the
build's processed status in App Store Connect before inviting testers. TestFlight
uses the same HTTPS account/OMR service as the packaged client.

Run the gate unit tests locally with:

```text
python -B apple/release/test_cloud_release.py
```

Those tests validate release boundaries using synthetic files and mocks; the
signed export, actual native model inference and Apple upload are verified only
by their respective real macOS/TestFlight runs.
