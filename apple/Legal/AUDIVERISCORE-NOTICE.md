# AudiverisCore provenance and copyright

This application links a modified, partial Swift translation of Audiveris image
filters and foreground run retrieval, retained for image preprocessing. It is
licensed under AGPL-3.0-or-later. The complete license is bundled beside this
notice as `AGPL-3.0-LICENSE.txt`. This is a modified subset, not an official
Audiveris release or a complete local music-recognition engine.

- Copyright © Audiveris 2026. Original authors: ryo/twitter `@xiaot_Tag`
  (adaptive/vertical filters), Hervé Bitteur (filters and run retrieval).
- Copyright © NoteLite 2026. The local Java source also credits NoteLite Contributors.
- Copyright © 2026 NoteLite contributors for the Swift adaptation, resource
  guards, cancellation support, Swift value types and tests.

Upstream: https://github.com/Audiveris/audiveris

Verified upstream source reference: Audiveris 5.10.0, commit
`b02fd4f8e31bf3dee1124bf4956e60fcca7f00a0`. The six Java source bodies listed
in `AUDIVERISCORE-PROVENANCE.json` match this reference after removing comments
and whitespace and restoring `com.notelite` package prefixes to `org.audiveris`.
This establishes a reproducible upstream reference, not a claim that this was
the unique historical fork point. The imported NoteLite history starts at
`22ea65a` (Initial release: NoteLite 5.10.3) without upstream Git ancestry;
the exact original fork point is unknown.

The translated sources are `apple/AudiverisCore/Sources/AudiverisCore/`:
`Binarization.swift`, `Image.swift` and `Runs.swift`. They adapt the Java files
under `app/src/main/java/com/notelite/omr/image/` (`AdaptiveFilter.java`,
`VerticalFilter.java`, `GlobalFilter.java`) and `.../run/`
(`RunsRetriever.java`, `RunTableFactory.java`, `RunTable.java`). The upstream
counterparts use `app/src/main/java/org/audiveris/omr/`.

Changes include Swift value types, checked dimensions/allocation, cancellation,
whole-image extraction and fixture tests. Java callback adapters, regional
selection, run rejection, threading and the remaining recognition pipeline
are absent from this partial package. It does not infer musical notes.

The top-level MIT license does not replace the AGPL license of derived code.
Original licenses continue to govern independently authored portions. Neither
the product name, packaging nor contributor status supplies an additional
copyright permission. No all-rights-holder App Store exception is asserted.

`SOURCE-OFFER.json` identifies this build's exact NoteLite commit, public source
archive, full translated-package hashes and source/build instructions. The
archive includes the linked application and build scripts, not only this
partial package. `CORRESPONDING-SOURCE.md` explains retrieval and rebuilding.
These resources provide notices and provenance; they do not establish that
App Store terms or installation-information requirements are satisfied.

This program is distributed WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the full
license for the terms.
