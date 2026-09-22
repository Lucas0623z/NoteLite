/* Copyright © NoteLite 2026. Released under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public class PianoBoosterLauncherTest
{
    @Rule public TemporaryFolder temporary = new TemporaryFolder();

    private Path program (Path path) throws Exception
    {
        Files.createDirectories(path.getParent());
        Files.createFile(path);
        path.toFile().setExecutable(true);
        return path.toAbsolutePath().normalize();
    }

    @Test public void preservesUnicodeSpacesAndShellMetacharactersAsOneArgument () throws Exception
    {
        Path root = temporary.newFolder("program with spaces").toPath();
        Path executable = root.resolve("PianoBooster.exe");
        Path midi = root.resolve("乐章 & $(echo).mid");
        List<String> arguments = PianoBoosterLauncher.command(executable, midi);
        assertEquals(2, arguments.size());
        assertEquals(executable.toAbsolutePath().toString(), arguments.get(0));
        assertEquals(midi.toAbsolutePath().toString(), arguments.get(1));
    }

    @Test public void configuredProgramWinsAndStaleConfigurationFallsBackToEnvironment () throws Exception
    {
        Path root = temporary.getRoot().toPath();
        Path configured = program(root.resolve("custom/PianoBooster.exe"));
        Path fallback = program(root.resolve("portable/PianoBooster.exe"));
        Map<String, String> environment = Map.of("NOTELITE_PIANOBOOSTER", fallback.toString());
        assertEquals(configured, PianoBoosterLauncher.find(configured.toString(), "Windows 11", environment, null).orElseThrow());
        assertEquals(fallback, PianoBoosterLauncher.find(root.resolve("gone.exe").toString(), "Windows 11", environment, null).orElseThrow());
    }

    @Test public void discoversTheOfficialVersionedWindowsInstallDirectory () throws Exception
    {
        Path root = temporary.newFolder("Program Files (x86)").toPath();
        Path expected = program(root.resolve("Piano Booster-1.0.0/pianobooster.exe"));
        assertEquals(expected, PianoBoosterLauncher.find("", "Windows 11",
                Map.of("ProgramFiles(x86)", root.toString()), null).orElseThrow());
    }

    @Test public void discoversPathEntriesWithSpaces () throws Exception
    {
        Path root = temporary.newFolder("my music apps").toPath();
        Path expected = program(root.resolve("PianoBooster.exe"));
        assertEquals(expected, PianoBoosterLauncher.find("", "Windows 11",
                Map.of("PATH", ";" + root + ";"), null).orElseThrow());
    }

    @Test public void resolvesMacApplicationBundleToItsExecutable () throws Exception
    {
        Path bundle = temporary.newFolder("PianoBooster.app").toPath();
        Path expected = program(bundle.resolve("Contents/MacOS/pianobooster"));
        assertEquals(expected, PianoBoosterLauncher.executable(bundle, "Mac OS X").orElseThrow());
    }

    @Test public void rejectsWindowsShellScriptsAndMissingPrograms () throws Exception
    {
        Path script = program(temporary.getRoot().toPath().resolve("pianobooster.cmd"));
        assertTrue(PianoBoosterLauncher.executable(script, "Windows 11").isEmpty());
        assertTrue(PianoBoosterLauncher.executable(script.resolveSibling("missing.exe"), "Windows 11").isEmpty());
    }

    @Test public void rejectsMalformedMidiBeforeLaunchingAnExecutable () throws Exception
    {
        String suffix = System.getProperty("os.name").startsWith("Windows") ? ".exe" : "";
        Path executable = Path.of(System.getProperty("java.home"), "bin", "java" + suffix);
        Path badMidi = temporary.newFile("invalid.mid").toPath();
        Files.writeString(badMidi, "not a MIDI file");
        try {
            PianoBoosterLauncher.launch(executable, badMidi);
            fail("Invalid MIDI must be rejected before process launch");
        } catch (java.io.IOException expected) {
            assertTrue(expected.getMessage().contains("Invalid MIDI"));
        }
    }
}
