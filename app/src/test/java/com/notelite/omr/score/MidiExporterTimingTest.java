/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.score;

import org.audiveris.proxymusic.ScorePartwise;
import org.audiveris.proxymusic.util.Marshalling;
import org.junit.Test;

import javax.sound.midi.MetaMessage;
import javax.sound.midi.MidiSystem;
import javax.sound.midi.Sequence;
import javax.sound.midi.ShortMessage;
import javax.sound.midi.Track;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;

/** Actual serialized MIDI evidence for repeat-entry tempo, printed/sounding offsets and ties. */
public class MidiExporterTimingTest
{
    @Test public void secondEndingKeepsTheTempoActuallyHeard () throws Exception {
        Sequence s = export("second-ending-tempo",
                measure("<barline location='left'><repeat direction='forward'/></barline>"
                        + tempo(60) + note("C", 480, "")),
                measure("<barline location='left'><ending number='1' type='start'/></barline>"
                        + tempo(120) + note("D", 480, "")
                        + "<barline location='right'><ending number='1' type='stop'/><repeat direction='backward'/></barline>"),
                measure("<barline location='left'><ending number='2' type='start'/></barline>"
                        + note("E", 480, "") + "<barline location='right'><ending number='2' type='stop'/></barline>"));
        assertEquals(List.of("1000000@0", "500000@480", "1000000@960"), tempos(s));
        assertEquals(3_500_000L, s.getMicrosecondLength());
        assertEquals(List.of("on60@0", "off60@480", "on62@480", "off62@960",
                "on60@960", "off60@1440", "on64@1440", "off64@1920"), notes(s));
    }

    @Test public void laterSoundOffsetPreservesEarlierPrintedTempo () throws Exception {
        Sequence s = export("printed-before-sound-offset", measure(printed("quarter", 0, "80")
                + "<sound tempo='120'><offset>960</offset></sound></direction>" + quarters()));
        assertEquals(List.of("750000@0", "500000@960"), tempos(s));
        assertEquals(2_500_000L, s.getMicrosecondLength());
    }

    @Test public void directionOffsetWithoutSoundYesMovesOnlyThePrintedTempo () throws Exception {
        Sequence s = export("printed-offset-default-no", measure(printed("quarter", 0, "80")
                + "<offset>480</offset><sound tempo='120'/></direction>" + quarters()));
        assertEquals(List.of("500000@0", "750000@480"), tempos(s));
        assertEquals(2_750_000L, s.getMicrosecondLength());
    }

    @Test public void soundWinsOverPrintedTempoAtTheSamePosition () throws Exception {
        Sequence s = export("sound-authority-same-offset", measure(printed("quarter", 0, "80")
                + "<offset sound='yes'>480</offset><sound tempo='120'/></direction>" + quarters()));
        assertEquals(List.of("500000@480"), tempos(s));
        assertEquals(2_000_000L, s.getMicrosecondLength());
    }

    @Test public void dottedMetronomeIsConvertedToQuarterNoteTempo () throws Exception {
        Sequence s = export("dotted-eighth-metronome", measure(printed("eighth", 1, "80")
                + "</direction>" + note("C", 480, "")));
        assertEquals(List.of("1000000@0"), tempos(s));
        assertEquals(1_000_000L, s.getMicrosecondLength());
    }

    @Test public void textualOmrMetronomeDoesNotBlockMidiExport () throws Exception {
        Sequence s = export("textual-metronome-fallback", measure(printed("quarter", 0, "80 env.")
                + "</direction>" + note("C", 480, "")));
        assertEquals(List.of(), tempos(s));
        assertEquals(500_000L, s.getMicrosecondLength());
    }

    @Test public void crossStaffSameVoiceTieSustainsOneAttack () throws Exception {
        Sequence s = export("cross-staff-tie", measure(tempo(60) + note("C", 480, tie("start", "1", 1))),
                measure(note("C", 480, tie("stop", "1", 2))));
        assertEquals(List.of("on60@0", "off60@960"), notes(s));
        assertEquals(2_000_000L, s.getMicrosecondLength());
    }

    @Test public void crossStaffTieChainKeepsItsInitialAttack () throws Exception {
        Sequence s = export("cross-staff-tie-chain", measure(note("C", 480, tie("start", "1", 1))),
                measure(note("C", 480, "<tie type='stop'/><tie type='start'/><voice>1</voice><staff>2</staff>")),
                measure(note("C", 480, tie("stop", "1", 1))));
        assertEquals(List.of("on60@0", "off60@1440"), notes(s));
    }

    @Test public void differentVoicesNeverMergeAcrossStaves () throws Exception {
        Sequence s = export("different-voice-ties", measure(note("C", 480, tie("start", "1", 1))),
                measure(note("C", 480, tie("stop", "2", 2))));
        assertEquals(List.of("on60@0", "off60@480", "on60@480", "off60@960"), notes(s));
    }

    @Test public void matchingStaffDisambiguatesSameVoiceUnisonTies () throws Exception {
        Sequence s = export("same-staff-tie-preference", measure(note("C", 480, tie("start", "1", 1))
                        + chord("C", 480, tie("start", "1", 2))),
                measure(note("C", 480, tie("stop", "1", 2)) + chord("C", 480, tie("stop", "1", 1))));
        assertEquals(List.of("on60@0", "on60@0", "off60@960", "off60@960"), notes(s));
    }

    @Test public void ambiguousCrossStaffTieRejectsRatherThanChoosingAnArbitraryNote () throws Exception {
        assertThrows(IllegalArgumentException.class, () -> export("ambiguous-cross-staff-tie",
                measure(note("C", 480, tie("start", "1", 1)) + chord("C", 480, tie("start", "1", 2))),
                measure(note("C", 480, tie("stop", "1", 3)))));
        assertFalse(Files.exists(evidence().resolve("ambiguous-cross-staff-tie.mid")));
    }

    @Test public void gapBetweenTieSegmentsIsNotFilledWithSound () throws Exception {
        Sequence s = export("gapped-tie", measure(note("C", 240, tie("start", "1", 1)) + rest(240)),
                measure(note("C", 240, tie("stop", "1", 1)) + rest(240)));
        assertEquals(List.of("on60@0", "off60@240", "on60@480", "off60@720"), notes(s));
    }

    @Test public void unfinishedTieEndsBeforeTheNextAttackAtTheSameTick () throws Exception {
        Sequence s = export("unfinished-tie-retrigger", measure(note("C", 480, tie("start", "1", 1))),
                measure(note("C", 480, "<voice>1</voice><staff>1</staff>")));
        assertEquals(List.of("on60@0", "off60@480", "on60@480", "off60@960"), notes(s));
    }

    @Test public void zeroLengthOmrNoteDoesNotLeaveAnUnmatchedAttack () throws Exception {
        Sequence s = export("zero-length-note", measure(note("C", 0, "") + note("D", 480, "")));
        assertEquals(List.of("on62@0", "off62@480"), notes(s));
    }

    private static Path evidence () {
        return Path.of("build", "midi-timing", System.getenv().getOrDefault("NOTELITE_MIDI_AUDIT_PHASE", "current"));
    }

    private static Sequence export (String name, String... measures) throws Exception {
        String xml = "<score-partwise version='4.0'><part-list><score-part id='P1'><part-name>Test</part-name>"
                + "</score-part></part-list><part id='P1'>" + String.join("", measures) + "</part></score-partwise>";
        Path dir = evidence(); Files.createDirectories(dir);
        Files.writeString(dir.resolve(name + ".musicxml"), xml, StandardCharsets.UTF_8);
        ScorePartwise score = (ScorePartwise) Marshalling.unmarshal(new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8)));
        Path target = dir.resolve(name + ".mid");
        Files.deleteIfExists(target);
        MidiExporter.write(score, target);
        Sequence s = MidiSystem.getSequence(target.toFile());
        Files.writeString(dir.resolve(name + ".json"), "{\"scope\":\"Locally compiled Java converter; actual MIDI file, not cloud OMR\","
                + "\"resolution\":" + s.getResolution() + ",\"microseconds\":" + s.getMicrosecondLength()
                + ",\"notes\":" + json(notes(s)) + ",\"tempos\":" + json(tempos(s)) + "}\n", StandardCharsets.UTF_8);
        return s;
    }

    private static String json (List<String> values) { return values.isEmpty() ? "[]" : "[\"" + String.join("\",\"", values) + "\"]"; }
    private static String measure (String content) { return "<measure number='1'><attributes><divisions>480</divisions></attributes>" + content + "</measure>"; }
    private static String note (String step, int duration, String content) {
        return "<note><pitch><step>" + step + "</step><octave>4</octave></pitch><duration>" + duration + "</duration>" + content + "</note>";
    }
    private static String chord (String step, int duration, String content) { return note(step, duration, content).replace("<note>", "<note><chord/>"); }
    private static String tie (String type, String voice, int staff) { return "<tie type='" + type + "'/><voice>" + voice + "</voice><staff>" + staff + "</staff>"; }
    private static String rest (int duration) { return "<note><rest/><duration>" + duration + "</duration></note>"; }
    private static String quarters () { return note("C", 480, "").repeat(4); }
    private static String tempo (int bpm) { return "<direction><sound tempo='" + bpm + "'/></direction>"; }
    private static String printed (String unit, int dots, String value) {
        return "<direction><direction-type><metronome><beat-unit>" + unit + "</beat-unit>" + "<beat-unit-dot/>".repeat(dots)
                + "<per-minute>" + value + "</per-minute></metronome></direction-type>";
    }
    private static List<String> notes (Sequence s) {
        List<String> result = new ArrayList<>(); Track t = s.getTracks()[1];
        for (int i = 0; i < t.size(); i++) if (t.get(i).getMessage() instanceof ShortMessage m) {
            if (m.getCommand() == ShortMessage.NOTE_ON && m.getData2() > 0) result.add("on" + m.getData1() + "@" + t.get(i).getTick());
            else if (m.getCommand() == ShortMessage.NOTE_OFF) result.add("off" + m.getData1() + "@" + t.get(i).getTick());
        }
        return result;
    }
    private static List<String> tempos (Sequence s) {
        List<String> result = new ArrayList<>(); Track t = s.getTracks()[0];
        for (int i = 0; i < t.size(); i++) if (t.get(i).getMessage() instanceof MetaMessage m && m.getType() == 0x51) {
            byte[] b = m.getData(); int value = (b[0] & 255) << 16 | (b[1] & 255) << 8 | b[2] & 255;
            result.add(value + "@" + t.get(i).getTick());
        }
        return result;
    }
}
