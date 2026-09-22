/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.score;

import org.audiveris.proxymusic.ScorePartwise;
import org.audiveris.proxymusic.util.Marshalling;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import javax.sound.midi.MetaMessage;
import javax.sound.midi.MidiSystem;
import javax.sound.midi.Sequence;
import javax.sound.midi.ShortMessage;
import javax.sound.midi.Track;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertTrue;

/** Playback regression tests beyond the fixed before/after audit corpus. */
public class MidiExporterAdvancedTest
{
    @Rule public TemporaryFolder tmp = new TemporaryFolder();

    @Test public void nestedRepeatsReplayTheInnerRepeatOnEachOuterPass () throws Exception {
        Sequence s = export(part(
                measure(start() + note("C", 480)),
                measure(start() + note("D", 480) + stop()),
                measure(note("E", 480) + stop())));
        assertEquals(List.of(60, 62, 62, 64, 60, 62, 62, 64), pitches(s, 1));
        assertEquals(8L * s.getResolution(), s.getTickLength());
    }

    @Test public void repeatRestoresDivisionsTransposeAndTempo () throws Exception {
        Sequence s = export(part(
                measure(start() + "<attributes><transpose><chromatic>-2</chromatic></transpose></attributes>" + note("C", 480)),
                measure("<attributes><divisions>960</divisions><transpose><chromatic>0</chromatic></transpose></attributes>"
                        + "<direction><sound tempo='60'/></direction>" + note("D", 960) + stop())));
        assertEquals(List.of(58, 62, 58, 62), pitches(s, 1));
        assertEquals(4L * s.getResolution(), s.getTickLength());
        List<String> tempos = new ArrayList<>();
        Track meta = s.getTracks()[0];
        for (int i = 0; i < meta.size(); i++) if (meta.get(i).getMessage() instanceof MetaMessage m && m.getType() == 0x51) {
            byte[] b = m.getData(); int value = (b[0] & 255) << 16 | (b[1] & 255) << 8 | b[2] & 255;
            tempos.add(value + "@" + meta.get(i).getTick() / s.getResolution());
        }
        assertEquals(List.of("1000000@1", "500000@2", "1000000@3"), tempos);
    }

    @Test public void repeatPrintedInOnePartRepeatsAllParts () throws Exception {
        Sequence s = export(part(measure(start() + note("C", 480) + stop())),
                part(measure(note("E", 480))));
        assertEquals(List.of(60, 60), pitches(s, 1));
        assertEquals(List.of(64, 64), pitches(s, 2));
    }

    @Test public void partsShareMeasureBoundariesAndKeepFinalRest () throws Exception {
        Sequence s = export(part(measure(note("C", 1920)), measure(note("D", 480) + "<note><rest/><duration>1440</duration></note>")),
                part(measure(note("E", 480)), measure(note("F", 480))));
        Track t = s.getTracks()[2]; List<Long> onsets = new ArrayList<>();
        for (int i = 0; i < t.size(); i++) if (t.get(i).getMessage() instanceof ShortMessage m
                && m.getCommand() == ShortMessage.NOTE_ON && m.getData2() > 0) onsets.add(t.get(i).getTick());
        assertEquals(List.of(0L, 4L * s.getResolution()), onsets);
        assertEquals(8L * s.getResolution(), s.getTickLength());
    }

    @Test public void fineDurationGridSurvivesMidiFileResolution () throws Exception {
        Sequence s = export(part(measure("<attributes><divisions>1000</divisions></attributes>" + note("C", 1))));
        assertTrue("Resolution must preserve a thousandth of a quarter note", s.getResolution() % 1000 == 0);
        assertEquals(s.getResolution() / 1000, s.getTickLength());
    }

    @Test public void melodicFallbackNeverUsesPercussionChannel () throws Exception {
        String[] parts = new String[15];
        java.util.Arrays.fill(parts, part(measure(note("C", 480))));
        Sequence s = export(parts);
        for (int track = 1; track < s.getTracks().length; track++) {
            Track t = s.getTracks()[track];
            for (int i = 0; i < t.size(); i++) if (t.get(i).getMessage() instanceof ShortMessage m)
                assertTrue("Channel ten is reserved for percussion", m.getChannel() != 9);
        }
    }

    @Test public void timeAndConcertKeySignaturesSurviveMidiRoundTrip () throws Exception {
        Sequence s = export(part(measure("<attributes><key><fifths>0</fifths><mode>major</mode></key>"
                + "<time><beats>6</beats><beat-type>8</beat-type></time>"
                + "<transpose><chromatic>-2</chromatic></transpose></attributes>" + note("C", 1440))));
        assertArrayEquals(new byte[] {6, 3, 36, 8}, signature(s.getTracks()[0], 0x58));
        assertArrayEquals(new byte[] {-2, 0}, signature(s.getTracks()[1], 0x59));
        assertEquals(List.of(58), pitches(s, 1));
    }

    @Test public void malformedOmrDurationDoesNotShiftFollowingMeasures () throws Exception {
        Sequence s = export(part(measure("<attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes>" + note("C", 1980)),
                measure(note("D", 1840)), measure(note("E", 1920))));
        List<Long> onsets = new ArrayList<>(); Track t = s.getTracks()[1];
        for (int i = 0; i < t.size(); i++) if (t.get(i).getMessage() instanceof ShortMessage m
                && m.getCommand() == ShortMessage.NOTE_ON && m.getData2() > 0) onsets.add(t.get(i).getTick());
        assertEquals(List.of(0L, 4L * s.getResolution(), 8L * s.getResolution()), onsets);
    }

    @Test public void implicitPickupKeepsItsShortDuration () throws Exception {
        String pickup = "<measure number='0' implicit='yes'><attributes><divisions>480</divisions>"
                + "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>" + note("C", 480) + "</measure>";
        Sequence s = export(part(pickup, measure(note("D", 1920))));
        assertEquals(5L * s.getResolution(), s.getTickLength());
    }

    private static byte[] signature (Track t, int type) {
        for (int i = 0; i < t.size(); i++) if (t.get(i).getMessage() instanceof MetaMessage m && m.getType() == type) return m.getData();
        return null;
    }

    private Sequence export (String... parts) throws Exception {
        StringBuilder xml = new StringBuilder("<score-partwise version='4.0'><part-list>");
        for (int i = 0; i < parts.length; i++) xml.append("<score-part id='P").append(i).append("'><part-name>Test</part-name></score-part>");
        xml.append("</part-list>");
        for (int i = 0; i < parts.length; i++) xml.append("<part id='P").append(i).append("'>").append(parts[i]).append("</part>");
        xml.append("</score-partwise>");
        ScorePartwise score = (ScorePartwise) Marshalling.unmarshal(new ByteArrayInputStream(xml.toString().getBytes(StandardCharsets.UTF_8)));
        Path output = tmp.newFile("test.mid").toPath(); MidiExporter.write(score, output);
        return MidiSystem.getSequence(output.toFile());
    }
    private static String part (String... measures) { return String.join("", measures); }
    private static String measure (String body) { return "<measure number='1'><attributes><divisions>480</divisions></attributes>" + body + "</measure>"; }
    private static String note (String step, int duration) { return "<note><pitch><step>" + step + "</step><octave>4</octave></pitch><duration>" + duration + "</duration></note>"; }
    private static String start () { return "<barline location='left'><repeat direction='forward'/></barline>"; }
    private static String stop () { return "<barline location='right'><repeat direction='backward'/></barline>"; }
    private static List<Integer> pitches (Sequence s, int track) {
        List<Integer> notes = new ArrayList<>(); Track t = s.getTracks()[track];
        for (int i = 0; i < t.size(); i++) if (t.get(i).getMessage() instanceof ShortMessage m
                && m.getCommand() == ShortMessage.NOTE_ON && m.getData2() > 0) notes.add(m.getData1());
        return notes;
    }
}
