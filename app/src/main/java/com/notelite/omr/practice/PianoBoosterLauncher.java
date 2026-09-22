/* Copyright © NoteLite 2026. Released under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;
import javax.sound.midi.InvalidMidiDataException;
import javax.sound.midi.MidiSystem;

/** Opens an independently installed PianoBooster using its documented MIDI-file argument. */
public final class PianoBoosterLauncher
{
    public static final String DOWNLOAD_URL = "https://www.pianobooster.org/download.html";

    private PianoBoosterLauncher () {}

    public static Optional<Path> find (String configured)
    {
        return find(configured, System.getProperty("os.name"), System.getenv(),
                System.getProperty("user.home"));
    }

    static Optional<Path> find (String configured, String os, Map<String, String> environment,
                               String userDirectory)
    {
        List<Path> candidates = new ArrayList<>();
        add(candidates, configured);
        add(candidates, environment.get("NOTELITE_PIANOBOOSTER"));
        boolean windows = os.toLowerCase(Locale.ROOT).startsWith("windows");
        if (windows) {
            for (String root : List.of("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")) {
                String directory = environment.get(root);
                if (directory != null && !directory.isBlank()) {
                    add(candidates, directory + File.separator + "PianoBooster" + File.separator + "PianoBooster.exe");
                    add(candidates, directory + File.separator + "Piano Booster" + File.separator + "pianobooster.exe");
                    add(candidates, directory + File.separator + "Piano Booster-1.0.0" + File.separator + "pianobooster.exe");
                    add(candidates, directory + File.separator + "Programs" + File.separator + "PianoBooster" + File.separator + "PianoBooster.exe");
                }
            }
        } else if (os.toLowerCase(Locale.ROOT).contains("mac")) {
            add(candidates, "/Applications/PianoBooster.app");
            if (userDirectory != null) add(candidates, userDirectory + "/Applications/PianoBooster.app");
        } else {
            add(candidates, "/usr/bin/pianobooster");
            add(candidates, "/usr/local/bin/pianobooster");
            add(candidates, "/snap/bin/pianobooster");
        }
        String searchPath = environment.getOrDefault("PATH", environment.getOrDefault("Path", ""));
        for (String directory : searchPath.split(Pattern.quote(windows ? ";" : ":"))) {
            // Empty PATH entries mean the current directory: do not discover arbitrary local programs.
            if (!directory.isBlank()) {
                add(candidates, directory + File.separator + (windows ? "PianoBooster.exe" : "pianobooster"));
            }
        }
        return candidates.stream().map(path -> executable(path, os)).flatMap(Optional::stream).findFirst();
    }

    private static void add (List<Path> candidates, String path)
    {
        if (path == null || path.isBlank()) return;
        try {
            candidates.add(Path.of(path));
        } catch (InvalidPathException ignored) {
            // An obsolete configured path should not stop normal discovery.
        }
    }

    public static Optional<Path> executable (Path selected)
    {
        return executable(selected, System.getProperty("os.name"));
    }

    static Optional<Path> executable (Path selected, String os)
    {
        Path path = selected.toAbsolutePath().normalize();
        String platform = os.toLowerCase(Locale.ROOT);
        if (platform.contains("mac") && Files.isDirectory(path)
                && path.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(".app")) {
            for (String name : List.of("pianobooster", "PianoBooster")) {
                Path binary = path.resolve("Contents/MacOS").resolve(name);
                if (Files.isRegularFile(binary) && Files.isExecutable(binary)) return Optional.of(binary);
            }
            return Optional.empty();
        }
        if (!Files.isRegularFile(path) || !Files.isExecutable(path)) return Optional.empty();
        if (platform.startsWith("windows")
                && !path.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(".exe")) {
            return Optional.empty();
        }
        return Optional.of(path);
    }

    static List<String> command (Path executable, Path midi)
    {
        // Pass each absolute path as one argument. Never use a shell, string concatenation or quoting.
        return List.of(executable.toAbsolutePath().normalize().toString(),
                midi.toAbsolutePath().normalize().toString());
    }

    public static Process launch (Path executable, Path midi) throws IOException, InterruptedException
    {
        Path binary = executable(executable).orElseThrow(() -> new IOException("Invalid PianoBooster executable: " + executable));
        if (!Files.isRegularFile(midi)) throw new IOException("MIDI file not found: " + midi);
        try {
            MidiSystem.getSequence(midi.toFile());
        } catch (InvalidMidiDataException ex) {
            throw new IOException("Invalid MIDI file: " + midi, ex);
        }
        Process process = new ProcessBuilder(command(binary, midi))
                .directory(binary.getParent().toFile())
                .redirectOutput(ProcessBuilder.Redirect.DISCARD)
                .redirectError(ProcessBuilder.Redirect.DISCARD)
                .start();
        if (process.waitFor(500, TimeUnit.MILLISECONDS) && process.exitValue() != 0) {
            throw new IOException("PianoBooster exited with code " + process.exitValue());
        }
        return process;
    }
}
