# macOS desktop build

The desktop app remains the full Java/Swing NoteLite editor. It builds separately for
Apple Silicon (`arm64`) and Intel (`x86_64`), with a matching bundled Java runtime and
native Tesseract/Leptonica libraries. End users do not need to install Java.

## Build on a Mac

Install JDK **21** for the Mac's architecture and Apple's **Command Line Tools for Xcode**.
Full Xcode is not required for this Java desktop target. The command line tools are
required by `jpackage` for the customized DMG icon and for signing. The iPhone/iPad
app has a separate Xcode build; see [the Apple client](../apple/README.md).

```sh
# Install Apple's tools once, if they are missing.
xcode-select --install

# Select an installed JDK 21; use arm64 on Apple Silicon, x86_64 on Intel.
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export PATH="$JAVA_HOME/bin:$PATH"
java -version
bash ./gradlew :app:test --tests com.notelite.omr.ui.MacApplicationTest
bash ./gradlew :packaging:jpackage -PinstallerType=DMG
```

The output is `packaging/build/dist/NoteLite-5.12.0-macosx-arm64.dmg` or
`NoteLite-5.12.0-macosx-x86_64.dmg`, depending on the JDK architecture. A JDK running
under Rosetta produces an Intel package. Do not override `targetOS` to pretend to
cross-compile an installer: the build rejects a mismatch between the native libraries
and the JRE. Use the corresponding Mac/JDK, or the CI workflow, for each architecture.

Icons are generated with macOS's built-in `sips` and `iconutil`; no Homebrew or
ImageMagick installation is performed. Tesseract language data is downloaded through
NoteLite's language settings and is not embedded in the installer.

## GitHub Actions

[macos-desktop.yml](../.github/workflows/macos-desktop.yml) runs on `macos-15`
(Apple Silicon) and `macos-15-intel`. It compiles the app, tests shortcut conversion,
builds a DMG, mounts it, verifies the launcher's architecture and runs the bundled
Java runtime and `NoteLite -help`, then recognizes the bundled `chula.png` score using
the packaged launcher and checks its MusicXML and MIDI output. Download the two unsigned DMGs from the workflow's
artifacts. The workflow does not publish a release or upload to an app store.

The following still need an interactive check on each Mac architecture before a release:

- About, Settings and Quit in the macOS application menu; cancelling the unsaved-work dialog.
- Command-O/S/W/Z and Command-Shift-Z; progress and memory widgets remain in the window.
- Opening an `.omr` project from Finder, opening a PDF/image, and actual OCR recognition.
- Retina display rendering and external monitors.

The packaged recognition smoke test does not replace interactive GUI or recognition-quality checks.

## Developer ID distribution

The default artifact is unsigned. To produce a signed DMG, install a valid Developer ID
Application certificate with its private key in the Mac's keychain, then pass the
identity's user-name portion to `jpackage`:

```sh
bash ./gradlew :packaging:jpackage -PinstallerType=DMG \
  -PmacSigningIdentity='Your Name (TEAMID)'
```

An optional `-PmacSigningKeychain=/path/to/build.keychain-db` selects another keychain.
No signing credentials are stored in this repository. After configuring a
`notelite-notary` credentials profile with Apple's `notarytool`, submit the signed
artifact and staple Apple's accepted ticket:

```sh
xcrun notarytool submit packaging/build/dist/NoteLite-5.12.0-macosx-arm64.dmg \
  --keychain-profile notelite-notary --wait
xcrun stapler staple packaging/build/dist/NoteLite-5.12.0-macosx-arm64.dmg
```

Only staple after notarization reports **Accepted**. Substitute `x86_64` for the Intel
artifact. Signing and notarization require the owner's Apple developer credentials
and are not performed by the unsigned CI workflow.

References: [Java 21 packaging requirements](https://docs.oracle.com/en/java/javase/21/jpackage/packaging-overview.html),
[Apple command line tools](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools),
[Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
