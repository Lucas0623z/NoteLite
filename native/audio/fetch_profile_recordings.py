"""Optional original-source benchmark setup; audio stays in the caller's ignored folder.

Use the bundled Python with numpy/soundfile. Downloads 18 predeclared VSCO2 CE
recordings, 3 original Iowa solo viola recordings, and, with --voice, vocadito
tracks 1/2/3 and both human note annotations. Selection precedes detector tests.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import zipfile

import numpy as np
import soundfile as sf

SAMPLE_COMMIT = "440300901dfe9275fd84e0b7763af1f8443ae62e"
SFZ_COMMIT = "6dd651d55dde97fd4028699be9d4481f26917891"
REPO = "https://github.com/sgossner/VSCO-2-CE"
SAMPLES = {
    "viola": ("ViolaEnsSusVib.sfz", "Strings/Viola Section/susvib", ["ViolaEns_susvib_C2_v2_1.wav", "ViolaEns_susvib_A3_v2_1.wav", "ViolaEns_susvib_B4_v2_1.wav"]),
    "harp": ("Harp.sfz", "Strings/Harp", ["KSHarp_G1_mp.wav", "KSHarp_C3_mf.wav", "KSHarp_F6_mf.wav"]),
    "oboe": ("OboeSusNV.sfz", "Woodwinds/Oboe/Sus", ["Oboe_Sus_A#2_v3_Main.wav", "Oboe_Sus_D4_v3_Main.wav", "Oboe_Sus_F5_v3_Main.wav"]),
    "horn": ("FHornSus.sfz", "Brass/F Horn/sus", ["MOHorn_sus_D#1_v3_1.wav", "MOHorn_sus_F2_v3_1.wav", "MOHorn_sus_F4_v1_1.wav"]),
    "trombone": ("TromboneSus.sfz", "Brass/Tenor Trombone/sus", ["tenortbn_sus_A#0_v2_1.wav", "tenortbn_sus_D2_v3_1.wav", "tenortbn_sus_F3_v3_1.wav"]),
    "tuba": ("TubaSus.sfz", "Brass/Tuba/sus", ["Tuba3_sus_F0_v1_rr1_Mid.wav", "Tuba3_sus_A#1_v3_rr1_Mid.wav", "Tuba3_sus_D3_v1_rr1_Mid.wav"]),
}

def fetch(url, path):
    if path.exists():
        return path.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "NoteLite-original-recording-benchmark"})
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data

def digest(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def raw(commit, path):
    return f"https://raw.githubusercontent.com/sgossner/VSCO-2-CE/{commit}/" + urllib.parse.quote(path, safe="/")

def main(folder, include_voice):
    folder.mkdir(parents=True, exist_ok=True)
    tree_data = fetch(f"https://api.github.com/repos/sgossner/VSCO-2-CE/git/trees/{SAMPLE_COMMIT}?recursive=1", folder / "VSCO-2-CE-tree.json")
    sfz_tree_data = fetch(f"https://api.github.com/repos/sgossner/VSCO-2-CE/git/trees/{SFZ_COMMIT}?recursive=1", folder / "VSCO-2-CE-sfz-tree.json")
    tree = {x["path"]: x["sha"] for x in json.loads(tree_data)["tree"] if x["type"] == "blob"}
    sfz_tree = {x["path"]: x["sha"] for x in json.loads(sfz_tree_data)["tree"] if x["type"] == "blob"}
    documents = {}
    for filename in ["LICENSE", "README.md", "Readme.txt"]:
        url = raw(SAMPLE_COMMIT, filename)
        data = fetch(url, folder / "documents" / filename)
        assert blob(data) == tree[filename], filename
        documents[filename] = {"url": url, "sha256": digest(data), "gitBlobSha": tree[filename]}
    jobs = []
    for instrument, (sfz, directory, filenames) in SAMPLES.items():
        url = raw(SFZ_COMMIT, sfz)
        data = fetch(url, folder / "documents" / sfz)
        assert blob(data) == sfz_tree[sfz], sfz
        documents[sfz] = {"url": url, "sha256": digest(data), "gitBlobSha": sfz_tree[sfz]}
        mapping = {}
        for region in re.split(r"<region>", data.decode("utf-8-sig"))[1:]:
            name = re.search(r"sample\s*=\s*(.+?)(?:\r?\n|$)", region)
            pitch = re.search(r"pitch_keycenter\s*=\s*(\d+)", region)
            if name and pitch:
                mapping[name.group(1).strip().replace("\\", "/").split("/")[-1]] = int(pitch.group(1))
        for filename in filenames:
            assert filename in mapping, (sfz, filename)
            jobs.append((instrument, directory + "/" + filename, mapping[filename], sfz))

    def download(job):
        instrument, relative, midi, sfz = job
        url = raw(SAMPLE_COMMIT, relative)
        target = folder / "samples" / relative
        data = fetch(url, target)
        assert blob(data) == tree[relative], relative
        audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        mono = np.mean(audio, axis=1, dtype=np.float32)
        pcm = target.with_suffix(".f32")
        pcm_data = mono.astype("<f4", copy=False).tobytes()
        pcm.write_bytes(pcm_data)
        return {"instrument": instrument, "label": Path(relative).stem, "expectedMidi": midi,
                "truth": "Numeric pitch_keycenter in original upstream SFZ; filename octave convention is not used as truth.",
                "truthSource": documents[sfz], "sourceUrl": url, "sourceSha256": digest(data), "sourceGitBlobSha": tree[relative],
                "license": "CC0-1.0", "source": "Versilian Studios / Sam Gossner / Ivy Audio / Simon Dalzell",
                "instrumentCaveat": "Viola section with vibrato; not a solo viola" if instrument == "viola" else None,
                "original": str(target.resolve()), "pcm": str(pcm.resolve()), "pcmSha256": digest(pcm_data),
                "sampleRate": rate, "channels": audio.shape[1], "samples": len(mono), "durationSeconds": len(mono) / rate,
                "decoder": f"soundfile {sf.__version__}; libsndfile {sf.__libsndfile_version__}"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        samples = list(pool.map(download, jobs))
    iowa_url = "https://theremin.music.uiowa.edu/sound%20files/MIS%20Pitches%20-%202014/Strings/Viola/Viola.arco.ff.sulC.stereo.zip"
    iowa_archive = fetch(iowa_url, folder / "iowa-viola.zip")
    assert digest(iowa_archive) == "5bc1565edd601b35e61acb2b16c8069a904dd56277e3219a2e72f337f548685a"
    for filename, url in [("Iowa-viola-2012.html", "https://theremin.music.uiowa.edu/MIS-Pitches-2012/MISViola2012.html"),
                          ("Iowa-terms.html", "https://theremin.music.uiowa.edu/MIS.html")]:
        data = fetch(url, folder / "documents" / filename)
        documents[filename] = {"url": url, "sha256": digest(data)}
    with zipfile.ZipFile(io.BytesIO(iowa_archive)) as z:
        for note, midi in [("C3", 48), ("C4", 60), ("C5", 72)]:
            name = f"Viola.arco.ff.sulC.{note}.stereo.aif"
            data = z.read(name); target = folder / "samples" / "Iowa" / name
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
            audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
            pcm_data = np.mean(audio, axis=1, dtype=np.float32).astype("<f4", copy=False).tobytes()
            pcm = target.with_suffix(".f32"); pcm.write_bytes(pcm_data)
            samples.append({"instrument": "viola", "label": Path(name).stem, "expectedMidi": midi,
                            "truth": "Original Iowa individual-note filename in scientific pitch notation, performer Manuel Tabora, 2012; not inferred by detector.",
                            "truthSource": documents["Iowa-viola-2012.html"], "sourceUrl": iowa_url, "archiveSha256": digest(iowa_archive), "sourceSha256": digest(data),
                            "license": "Iowa public permission: download/use for any projects without restrictions; see original MIS.html. Not relabeled CC0.",
                            "source": "Lawrence Fritts / University of Iowa Electronic Music Studios; Manuel Tabora (viola)",
                            "instrumentCaveat": "Solo arco ff, played on C string, original anechoic recording; not room validation.",
                            "original": str(target.resolve()), "pcm": str(pcm.resolve()), "pcmSha256": digest(pcm_data), "sampleRate": rate,
                            "channels": audio.shape[1], "samples": len(audio), "durationSeconds": len(audio)/rate,
                            "decoder": f"soundfile {sf.__version__}; libsndfile {sf.__libsndfile_version__}"})
    manifest = {"schemaVersion": 1, "repository": REPO, "sampleCommit": SAMPLE_COMMIT, "mappingCommit": SFZ_COMMIT,
                "attribution": "Versilian Studios / Sam Gossner and Ivy Audio / Simon Dalzell; CC0-1.0. Iowa solo viola: Lawrence Fritts / Manuel Tabora; original unrestricted project-use permission.",
                "sourceDocuments": documents, "sampling": "Three fixed VSCO source files per instrument predeclared in SAMPLES; three Iowa solo viola C3/C4/C5 source files. All including failures.",
                "localProcessing": "Original WAV preserved; native-rate float32 decode, stereo averaged to mono, no gain/denoise/tuning/trimming.",
                "limitation": "Original single-note library recordings; VSCO upstream cutting/possible tuning. VSCO viola is a section, Iowa is solo. This is not a live instrument/room/user usability test. No independent onset/offset truth for library samples.",
                "uncovered": [{"instrument": "euphonium", "reason": "No actual euphonium in inspected original VSCO2 CE/VCSL/Iowa sample catalogues. No substituted tuba/trombone is counted."}],
                "samples": samples}
    if include_voice:
        record_url = "https://zenodo.org/api/records/5578807"
        record_data = fetch(record_url, folder / "vocadito-record.json")
        record = json.loads(record_data)
        assert record["metadata"]["license"]["id"] == "cc-by-4.0"
        item = next(x for x in record["files"] if x["key"] == "vocadito.zip")
        archive = fetch(item["links"]["self"], folder / "vocadito.zip")
        assert hashlib.md5(archive).hexdigest() == "dea40fd18f14d899643c4ba221b33a46"
        voice = {"sourceUrl": record_url, "archiveUrl": item["links"]["self"], "archiveSha256": digest(archive),
                 "archiveMd5": hashlib.md5(archive).hexdigest(), "license": "CC-BY-4.0",
                 "attribution": "Rachel M. Bittner, Katherine Pasalo, Juan Jose Bosch, Gabriel Meseguer-Brocal, David Rubinstein (vocadito, 2021)",
                 "tracks": [1, 2, 3], "truth": "Both independent human note annotations retained; not detector-generated truth.",
                 "localProcessing": "Original complete WAV and CSV annotations extracted unchanged; no trimming or tuning.", "files": []}
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for name in z.namelist():
                if re.search(r"(?:^|/)vocadito_(?:1|2|3)(?:[_.]|$)", name) or Path(name).name.lower() in ["readme.md", "readme.txt", "license", "vocadito_metadata.csv"]:
                    if name.endswith("/"): continue
                    target = folder / "vocadito" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = z.read(name); target.write_bytes(data)
                    voice["files"].append({"name": name, "path": str(target.resolve()), "sha256": digest(data)})
        manifest["voice"] = voice
    target = folder / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(target.resolve()), "samples": len(samples), "profiles": 6, "voiceIncluded": include_voice, "uncovered": "euphonium"}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--voice", action="store_true")
    args = parser.parse_args()
    main(args.folder.resolve(), args.voice)
