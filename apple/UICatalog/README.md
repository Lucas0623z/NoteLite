# UI documentation capture (test branch only)

This suite uses the real SwiftUI library, details, settings, privacy, history and review views.
It does not run Audiveris or contact a server. Every capture displays a mock-data watermark.

The fixture route is compiled only with `DEBUG` and requires `--ui-catalog`.
`NOTELITE_UI_CATALOG_SCENE` selects one of the documented scenarios. Each process uses a
fresh temporary library, a private UserDefaults suite, generated PDF staff notation, and the
bundled demo MusicXML. Practice history and exported artifacts are simulated data, not
measured playing/recognition results. An injected `EmbeddedRecognizing` implementation
advertises the iOS local-engine capability without loading native runtime components.
macOS shows the basic client's server configuration branch.

`UICatalogUITests` captures 13 scenes on iPhone, iPad and macOS, plus iPad library landscape.
Names begin `MOCK-<platform>-<scene>-<orientation>`. The macOS `portrait` suffix is the
cross-platform default capture variant, not a claim that the Mac window is portrait.
Feedback and result details are scrolled into view on iPhone.

This branch is documentation tooling, not an App Store release. It must not be merged or
used for signing/uploading a production app. No recognition quality or microphone accuracy
is established by these screenshots. System file/share/permission dialogs are not simulated.

Run the `Apple clients` workflow manually on `codex/ui-inventory`. It only builds Debug
clients and runs `UICatalogUITests`; screenshots and complete xcresult bundles are artifacts.
