# Copyright and provenance

AudiverisCore contains a modified, partial Swift translation of Audiveris image
filters and foreground run retrieval. This package is licensed under the
GNU Affero General Public License, version 3 or (at your option) any later
version. The full license is in [LICENSE](LICENSE).

- Copyright © Audiveris 2026. Original authors: ryo/twitter `@xiaot_Tag`
  (adaptive/vertical filters), Hervé Bitteur (filters and run retrieval).
- Copyright © NoteLite 2026. The Java source in this repository also credits
  NoteLite Contributors.
- Copyright © 2026 NoteLite contributors for the Swift adaptation, resource
  guards, cancellation support, Swift value types, and tests.

The algorithms were translated from these local source files:

- `app/src/main/java/com/notelite/omr/image/AdaptiveFilter.java`
- `app/src/main/java/com/notelite/omr/image/VerticalFilter.java`
- `app/src/main/java/com/notelite/omr/image/GlobalFilter.java`
- `app/src/main/java/com/notelite/omr/run/RunsRetriever.java`

The upstream project is <https://github.com/Audiveris/audiveris>. Upstream
counterparts live under `app/src/main/java/org/audiveris/omr/`. Their original
author attribution and AGPL notice are preserved here and in the translated
source headers. The repository's top-level license does not replace the AGPL
license of these derived files.

This is a modified subset, not an official Audiveris release. The Swift API
currently supports whole-image run extraction. Java callback adapters, region
selection, run rejection, threading, and the remaining recognition pipeline
are not part of this package. No musical notes are inferred by this subset.

This program is distributed WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See LICENSE
for the full terms.

The Java oracle fixture manifest records SHA-256 hashes of the original local
sources used to generate the expected outputs. Fixtures are test data, not
recognition results produced by the Swift implementation.
