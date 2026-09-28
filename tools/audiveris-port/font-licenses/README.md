# Bundled font notices and provenance

Audited on 2026-09-28 against the seven unmodified fonts in `app/res`.
`embedded-probe.gradle` copies this directory to `licenses/fonts` in both
the embedded acceptance probe and the complete NoteLite application's resources.
These notices cover the same font bytes copied into `assets` and
`runtime/lib/fonts`.

`FONT-NOTICES.txt` preserves the copyright, version, trademark, author,
description and license records from each actual font's OpenType/TrueType
`name` table. `provenance.json` records font hashes, exact upstream matches,
download sources and the hashes of the unchanged publisher license files.
No font was replaced, modified or assigned the repository's AGPL license.

## Retrieved publisher licenses

| Bundled file | Exact source match | Included license |
| --- | --- | --- |
| Bravura.otf, 1.392 | [Steinberg release commit 301087c](https://github.com/steinbergmedia/bravura/tree/301087ca0b0d30b65d81bc3e718ff64b613e2a9a) | Bravura-LICENSE.txt, SIL OFL 1.1 |
| Leland.otf, 0.77 | [MuseScore release commit 667d9b3](https://github.com/MuseScoreFonts/Leland/tree/667d9b3d95932236a3569d3994794b19e4084124) | Leland-LICENSE.txt, SIL OFL 1.1 |
| FinaleJazz.otf, 1.9 | MakeMusic's official MMFonts.msi | MakeMusic-OFL.txt, SIL OFL 1.1 |
| FinaleJazzText.otf, 1.3 | MakeMusic's official MMFonts.msi | MakeMusic-OFL.txt, SIL OFL 1.1 |

The [MakeMusic publisher article](https://makemusic.zendesk.com/hc/en-us/articles/1500013053461-MakeMusic-Fonts-and-Licensing-Information)
explicitly lists Finale Jazz and Finale Jazz Text and supplies both the
installer and the OFL attachment. Their extracted installer files match the
bundled fonts byte for byte. The embedded metadata still refers to the product
EULA; that text is preserved alongside the separately supplied OFL document.

Bravura's license file says 2019 while its embedded notice says 2021.
Leland's license file says 2022 while its embedded license notice says 2021.
Both sets of original notices are retained without correcting those dates.

## Unresolved legacy font terms

The following are provenance findings, not replacement license grants:

- **JazzPerc.ttf** matches the legacy file in the same official MakeMusic
  installer byte for byte. Its embedded notice credits Sigler Music Fonts
  (1995), with a 1999 Fontographer version and no license description or URL.
  The [Finale 27 release notes](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/What_s_new.htm)
  describe an OFL release of shipped fonts, while the current licensing
  article specifically lists OpenType Finale families. That article does not
  explicitly identify this older JazzPerc TrueType file. Its license scope
  remains unverified here; the MakeMusic license is not silently assigned to it.
- **Primus.ttf** matches the font linked by the
  [Indigo2 PriMus distributor FAQ](https://www.indigo2.dk/primus/faq/faq.htm)
  and the [original Audiveris import](https://github.com/Audiveris/audiveris/commit/63bec919570fd55ae91717fbdea43c12bef90f9c).
  Its embedded notice is Christof Schardt's 2008 copyright with all rights
  reserved, version 1.239. There are no embedded license fields. The
  [publisher's manual](https://www.columbussoft.de/download/primus11.pdf)
  does not provide a separate font redistribution grant; none was located.
- **MusicalSymbols.ttf** matches the
  [2013 Audiveris binary](https://raw.githubusercontent.com/Audiveris/audiveris/cb6f5d33b308b2446709ca34d0a7979879e4289a/res/MusicalSymbols.ttf).
  Its copyright and version records are empty and no license fields exist.
  [Audiveris's historical source](https://github.com/Audiveris/audiveris/blob/cb6f5d33b308b2446709ca34d0a7979879e4289a/src/main/omr/ui/symbol/MusicFont.java)
  names a now unavailable third-party download page. No verifiable original
  author license was located.

This directory preserves available evidence; it does not resolve those three
legacy terms. Retain these gaps when preparing distribution attribution.
