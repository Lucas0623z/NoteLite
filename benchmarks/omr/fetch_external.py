"""Download two pre-existing freely licensed Mutopia editions and their paired MIDI.

The reference MIDI is provided by the publisher, not produced by NoteLite.
These are digitally engraved PDFs (not photographs), submitted directly to OMR.
Mutopia's published MIDI plays the printed measures once, without volta expansion.
"""
import argparse
import json
from pathlib import Path
import urllib.request

from benchmark import read_midi, sha, write_midi

SOURCES = [
    {"id": "08_mutopia_minuet", "description": "Petzold Menuet in G BWV Anh. 114; Mutopia ID 75; 32 printed measures; published MIDI, repeats unexpanded; grace note included",
     "repeat_sections_beats": [[0, 48], [48, 96]],
     "license": "Public Domain (typesetter Allen Garvin)",
     "page": "https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=75",
     "base": "https://www.mutopiaproject.org/ftp/BachJS/BWVAnh114/anna-magdalena-04/anna-magdalena-04"},
    {"id": "09_mutopia_mozart", "description": "Mozart Piano Sonata K545 first movement; Mutopia published complete score and MIDI; repeats unexpanded",
     "repeat_sections_beats": [[0, 112], [112, 292]],
     "license": "Creative Commons Attribution-ShareAlike 3.0 Unported; typesetter Alejandro Sierra, copyright 2007; https://creativecommons.org/licenses/by-sa/3.0/",
     "page": "https://www.ibiblio.org/pub/multimedia/mutopia/MozartWA/KV545/K545-1/",
     "base": "https://www.ibiblio.org/pub/multimedia/mutopia/MozartWA/KV545/K545-1/K545-1"},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    args.fixtures.mkdir(parents=True, exist_ok=True)
    manifest = {"kind": "independent published Mutopia digital PDF editions, not photos; publisher MIDI truth with repeats unexpanded", "fixtures": []}
    for source in SOURCES:
        folder = args.fixtures / source["id"]
        folder.mkdir(exist_ok=True)
        urls = {"source.ly": source["base"] + ".ly", "reference.mid": source["base"] + ".mid", "score.pdf": source["base"] + "-a4.pdf"}
        for filename, url in urls.items():
            path = folder / filename
            if not path.exists():
                with urllib.request.urlopen(url) as response:
                    path.write_bytes(response.read())
        notes, hanging = read_midi(folder / "reference.mid")
        assert not hanging
        (folder / "truth.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")
        expanded = []
        destination = 0
        for start, stop in source["repeat_sections_beats"]:
            for repetition in range(2):
                expanded.extend({**note, "onset": note["onset"] - start + destination}
                                for note in notes if start <= note["onset"] < stop)
                destination += stop - start
        (folder / "truth-expanded.json").write_text(json.dumps(expanded, indent=2), encoding="utf-8")
        write_midi(expanded, folder / "reference-expanded.mid")
        manifest["fixtures"].append({"id": source["id"], "description": source["description"],
                                     "input": "score.pdf", "reference_notes": len(notes), "source_page": source["page"],
                                     "expanded_reference_notes": len(expanded), "repeat_sections_beats": source["repeat_sections_beats"],
                                     "repeat_verification": "Minuet: printed bars 1-16 and 17-32, 3/4. Mozart: printed bars 1-28 and 29-73, 4/4; verified from original PDF and LilyPond repeat blocks.",
                                     "source_urls": urls, "sha256": {name: sha(folder / name) for name in urls},
                                     "license": source["license"]})
    (args.fixtures / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
