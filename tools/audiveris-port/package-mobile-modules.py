#!/usr/bin/env python3
"""Create a full iOS module image with matching host OpenJDK tools.

Follows openjdk-mobile/ios-tools' jmod-from-target-classes approach, retaining
module configuration, resource data and legal notices needed beyond java.base.
Native code is supplied by separately linked static archives, never by dylibs.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("host_tools", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build, source, host, output = [p.resolve() for p in
                                  (args.build, args.source, args.host_tools, args.output)]
    modules = build / "jdk/modules"
    jmods = output / "jmods"
    runtime = output / "runtime"
    if jmods.exists() or runtime.exists():
        raise SystemExit("Output already exists; use a fresh build directory")
    if (host / "notelite-source-commit").read_text().strip() != "c1ed06aaef34c8dccf71e236d1ffa20918a77cfb":
        raise SystemExit("Host tools were not built from the pinned runtime source")
    jmods.mkdir(parents=True)
    count = 0
    for module in sorted(modules.iterdir()):
        if not module.is_dir() or not (module / "module-info.class").is_file():
            continue
        command = [str(host / "bin/jmod"), "create", "--class-path", str(module),
                   "--target-platform", "ios-aarch64"]
        configuration = build / "support/modules_conf" / module.name
        if configuration.is_dir():
            command += ["--config", str(configuration)]
        libraries = build / "support/modules_libs" / module.name
        if libraries.is_dir():
            resources = output / "module-data" / module.name
            for entry in libraries.rglob("*"):
                if not entry.is_file():
                    continue
                # Static archives live outside the module image. Never ship a
                # host/target dynamic library accidentally through this path.
                if entry.suffix in {".a", ".dylib", ".so", ".dll", ".diz", ".pdb"}:
                    continue
                if ".dSYM" in entry.as_posix():
                    continue
                target = resources / entry.relative_to(libraries)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry, target)
            if resources.exists():
                command += ["--libs", str(resources)]
        legal = [build / "support/modules_legal/common"]
        specific_legal = build / "support/modules_legal" / module.name
        if specific_legal.is_dir():
            legal.append(specific_legal)
        else:
            legal += [source / "src" / module.name / target / "legal"
                      for target in ("share", "unix", "macosx", "ios")]
        legal = [str(path) for path in legal if path.is_dir()]
        if legal:
            command += ["--legal-notices", os.pathsep.join(legal)]
        command.append(str(jmods / f"{module.name}.jmod"))
        subprocess.run(command, check=True)
        count += 1
    required = {"java.base", "java.desktop", "java.xml", "java.logging", "java.prefs",
                "java.naming", "java.management", "java.sql", "java.net.http",
                "jdk.unsupported", "jdk.charsets", "jdk.zipfs"}
    missing = [name for name in sorted(required) if not (jmods / f"{name}.jmod").is_file()]
    if missing:
        raise SystemExit("Missing target modules: " + ", ".join(missing))
    subprocess.run([str(host / "bin/jlink"), "--module-path", str(jmods),
                    "--add-modules", "ALL-MODULE-PATH", "--endian", "little",
                    "--release-info", str(build / "jdk/release"),
                    "--no-header-files", "--no-man-pages", "--output", str(runtime)], check=True)
    for required_file in ("lib/modules", "lib/tzdb.dat", "conf/security/java.security", "release"):
        if not (runtime / required_file).is_file():
            raise SystemExit(f"Missing runtime resource: {required_file}")
    print(f"Created iOS runtime module image from {count} target modules")


if __name__ == "__main__":
    main()
