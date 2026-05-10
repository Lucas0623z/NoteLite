# NoteLite

<div align="center">

**An OMR-based platform for lightweight score structuring, error detection, and music-education evaluation**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v5.11.0-brightgreen.svg)](https://github.com/Lucas0623z/NoteLite/releases/latest)
[![Status](https://img.shields.io/badge/status-In%20Development-yellow.svg)]()
[![GitHub](https://img.shields.io/badge/GitHub-Lucas0623z-blue?logo=github)](https://github.com/Lucas0623z)

[Features](#features) • [Architecture](#architecture) • [Installation](#installation) • [Roadmap](#roadmap) • [Contact](#contact)

</div>

---

## Overview

NoteLite is a smart score-processing platform aimed at music-education scenarios. Built on Optical Music Recognition (OMR), combined with lightweight encoding, score matching, and error detection, it forms a complete loop from "scan recognition" to "database management" to "teaching feedback".

### Background & Motivation

Existing OMR tools (Audiveris, oemer, homr, etc.) can already convert score images into machine-readable formats such as MusicXML, but several gaps remain for real music-education platforms:

- No lightweight structured representation suitable for database storage
- No automatic matching and diffing against canonical scores
- No suspected-error detection on scanned scores
- No audio-based assessment of performance correctness

NoteLite is designed to fill these gaps. **It is not another OMR engine** — it builds an education-oriented application layer on top of mature open-source OMR.

---

## Latest Release (v5.11.0, 2026-04-29)

NoteLite is currently a fork of the Audiveris OMR engine. The released desktop build includes:

- **Full OMR pipeline**: PDF / image → transcription → MusicXML export
- **MIDI export** (new in this release): file-type dropdown supports `.mxl` / `.xml` / `.mid`, with no need for MuseScore or other external tools
- **Chinese UI**: full zh_CN localization of menus / dialogs / toolbars
- **JDK 21 build**: extract and run, no compilation needed

Download: [`NoteLite-5.11.0.zip`](https://github.com/Lucas0623z/NoteLite/releases/latest)

> MIDI export is intended for proof-listening only. The first version uses a fixed velocity of 80; advanced features such as drum kits, repeat marks, and transposing instruments are not yet supported. See the release notes for details.

---

## Features

### Core Modules

| Module | Description | Status |
|--------|-------------|--------|
| **Score Recognition** | Recognize scanned, photographed, and PDF scores | In progress |
| **Lightweight Encoding** | Convert scores into compact structured data optimized for storage and retrieval | In progress |
| **Score Matching** | Auto-match against canonical scores with sequence-level diffing | Planned |
| **Smart Correction** | Detect missing/wrong notes, rhythm anomalies, accidental errors, etc. | Planned |
| **Performance Assessment** | Coarse-grained performance evaluation based on audio recognition | Planned |

### Highlights

1. **Lightweight score encoding**
   A compressed representation designed for databases — far smaller than full MusicXML.

2. **Canonical-score-driven diffing**
   New scans are not just recognized; they are also automatically validated against the canonical version in the database.

3. **Education-oriented closed loop**
   An end-to-end flow from paper score to online teaching feedback.

---

## Architecture

### System Layers

```
┌─────────────────────────────────────────────────┐
│                Application Layer                 │
│   Upload | Matching | Correction | Assessment   │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│            Database & Retrieval Layer           │
│   Canonical | User Uploads | Versions | Index   │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│              Lightweight Encoding               │
│   Relative pitch | Tokenize | Hash | Compress   │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│             Score Structuring Layer             │
│  Clef | Key | Time | Notes | Duration | Marks   │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│               OMR Recognition Layer             │
│  Preprocess | Staff detection | Symbols | Pitch │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│                   Input Layer                   │
│   Scanned image | Photo | PDF | Audio recording │
└─────────────────────────────────────────────────┘
```

### Tech Stack

- **OMR engine**: Audiveris / oemer / homr (alternative options)
- **Data formats**: MusicXML, JSON, custom compressed format
- **Matching algorithms**: edit distance, dynamic programming, hash fingerprints
- **Audio recognition**: TBD (for performance assessment)

---

## Installation

### Option 1: Direct Download (Recommended)

For end users — no compilation required:

1. Download `NoteLite-5.11.0.zip` from [Releases](https://github.com/Lucas0623z/NoteLite/releases/latest)
2. Extract anywhere
3. Run `bin/NoteLite.bat` (Windows) or `bin/NoteLite` (Linux/macOS)
4. Requires **Java 21** runtime on the machine

### Option 2: Build from Source

For development or contribution:

```bash
# Clone the repo
git clone https://github.com/Lucas0623z/NoteLite.git
cd NoteLite

# Use JDK 21 (verify with `java -version` showing 21.x)
export JAVA_HOME=/path/to/jdk-21

# Run
./gradlew :app:run --no-daemon

# Build a distribution
./gradlew :app:distZip --no-daemon
# Artifact at app/build/distributions/app-<version>.zip
```

On Windows, use `.\gradlew` instead of `./gradlew`.

### Long-Term Plan (Education-Platform Layer)

The education layer (lightweight encoding / canonical matching / performance assessment) is still in design. It will eventually introduce:

- Python 3.8+ (matching algorithms / data processing)
- Node.js 16+ (frontend)
- PostgreSQL / MySQL (database)

---

## Database Design

### Core Tables

#### 1. Score Master Table (`scores`)

| Column | Type | Description |
|--------|------|-------------|
| score_id | INT | Primary key |
| title | VARCHAR | Title |
| composer | VARCHAR | Composer |
| key_signature | VARCHAR | Key signature |
| time_signature | VARCHAR | Time signature |
| measure_count | INT | Number of measures |
| canonical_version_id | INT | Canonical version ID |

#### 2. Score Content Table (`score_content`)

| Column | Type | Description |
|--------|------|-------------|
| score_id | INT | Foreign key |
| raw_musicxml | TEXT | Original MusicXML |
| structured_json | JSON | Structured data |
| compressed_code | VARCHAR | Lightweight encoding |
| midi_url | VARCHAR | MIDI file path |

#### 3. Comparison Result Table (`comparisons`)

| Column | Type | Description |
|--------|------|-------------|
| compare_id | INT | Primary key |
| uploaded_score_id | INT | Uploaded score ID |
| matched_standard_id | INT | Matched canonical score ID |
| similarity_score | FLOAT | Similarity score |
| error_positions | JSON | Error positions |

---

## Roadmap

### Phase 1: MVP (Current)

- [x] Project architecture design
- [x] OMR engine integration (Audiveris fork, v5.10.x)
- [x] Structured-data output (MusicXML / MIDI)
- [x] Chinese UI localization (v5.10.0+)
- [x] Bundled MIDI export (v5.11.0)
- [ ] Lightweight-encoding implementation
- [ ] Initial database setup

### Phase 2: Canonical Matching & Correction

- [ ] Build canonical-score database
- [ ] Score-fingerprint index
- [ ] Diff-analysis algorithms
- [ ] Error-highlight UI

### Phase 3: Recognition Improvements

- [ ] Phone-photo scenario tuning
- [ ] Fine-tuning on teaching-score samples
- [ ] Misrecognition-rule fixes

### Phase 4: Performance Assessment

- [ ] Audio upload
- [ ] Pitch / rhythm extraction
- [ ] Comparison against canonical scores
- [ ] Learning-report generation

---

## Lightweight Encoding Example

### Design Idea

MusicXML is verbose and ill-suited for large-scale database storage. NoteLite uses a custom lightweight format:

```
# MusicXML (hundreds of lines)
<score-partwise>
  <part id="P1">
    <measure number="1">
      <note>
        <pitch><step>G</step><octave>4</octave></pitch>
        <duration>1</duration>
        <type>quarter</type>
      </note>
      ...
    </measure>
  </part>
</score-partwise>

# NoteLite encoding (single line)
TS:4/4;KS:G;M1:G4/q,A4/q,B4/h|M2:C5/q,B4/q,A4/h

# Token form (relative pitch)
4/4|G|+0:q,+2:q,+4:h|+5:q,+4:q,+2:h
```

**Benefits**:
- 90%+ reduction in storage size
- Simple database indexing
- Efficient similar-score matching
- Friendly to version management

---

## Technical Notes

### Score-Matching Algorithm

A multi-stage retrieval strategy:

1. **Coarse filter**: key signature + time signature + measure count
2. **Mid filter**: melody fingerprint hash
3. **Fine filter**: sequence-level edit distance

### Diff-Detection Capabilities

| Error Type | Method | Example |
|------------|--------|---------|
| Missing/extra notes | Sequence-length comparison | Canonical 8 notes, scan 7 notes |
| Wrong pitch | Per-symbol comparison | Canonical C5, scan D5 |
| Wrong duration | Rhythm-pattern matching | Canonical quarter note, scan eighth |
| Missing accidentals | Tonality analysis | Canonical F#, scan F |
| Measure-beat anomaly | Beat accumulation | Sum of durations in 4/4 measure ≠ 4 beats |

---

## Development Conventions

This project is currently maintained solely by the author and does not accept external pull requests. For issues or suggestions, please use the contact info below.

- Code style: existing Audiveris Java conventions (see `dev/jalopy/java-convention.xml`)
- Build: JDK 21 + Gradle
- Commit messages: [Conventional Commits](https://www.conventionalcommits.org/)
- Docs: Javadoc required for public APIs

---

## License

This project is released under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## Author

**Yuexuan Zhang**

Undergraduate, University of Illinois Urbana-Champaign (UIUC)
Research interests: computer science, intelligent systems, education technology, music information processing

### Contact

- **Email**: Lucas.z0623@outlook.com
- **GitHub**: [@Lucas0623z](https://github.com/Lucas0623z)
- **Personal site**: [https://personal-website-tau-lake.vercel.app/](https://personal-website-tau-lake.vercel.app/)

---

## Acknowledgements

Thanks to the following open-source projects and communities:

- [Audiveris](https://github.com/Audiveris/audiveris) — classic OMR framework
- [oemer](https://github.com/BreezeWhite/oemer) — modern deep-learning OMR
- [homr](https://github.com/TimeEscaper/homr) — end-to-end OMR model
- The broader GitHub open-source community for years of work in music information retrieval

---

## Project Status

- **Current version**: v5.11.0 (desktop OMR + MIDI export)
- **Status**: actively developed
- **Last updated**: 2026-04-29

---

<div align="center">

**If this project helps you, please consider giving it a Star**

Made by [Yuexuan Zhang](https://github.com/Lucas0623z)

</div>
