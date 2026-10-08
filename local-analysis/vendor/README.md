# Upstream provenance

* aubio 0.4.9 official source: https://aubio.org/pub/aubio-0.4.9.tar.bz2
  SHA-256 `d48282ae4dab83b3dc94c16cf011bcb63835c1c02b515490e1883049c3d1f3da`.
  `src/`, `wscript`, `COPYING` retained verbatim. Native adapter/build configuration
  lives in `native/audio`.
* Nakamura published AlignmentTool_v240109:
  https://midialignment.github.io/AlignmentTool_v240109.zip
  SHA-256 `cf75af54435c6ad83a7b578b691724866f6df5701e8529d86ae2a3db1e85bddd`.
  `Code/`, original pipeline scripts and `LICENCE.txt` retained verbatim.
  Windows build supplies missing `M_PI` externally.
* Official CREPE source/license commit `c9b71ce61491454125a0693f584f7244f29d9884`:
  https://github.com/marl/crepe. `upstream_core.py` is the comparison reference.
  `crepe_onnx.py` implements the same tiny layers, normalization and decoding.
  Official weights commit `bb29b8d99a89924476d112d27ed470e4ac5617c0`;
  archive/SHA-256 are in `windows-lock.json`. Weights ship locally after installation.
