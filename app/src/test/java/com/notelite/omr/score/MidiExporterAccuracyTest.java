/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.score;

import org.audiveris.proxymusic.Attributes;
import org.audiveris.proxymusic.Backup;
import org.audiveris.proxymusic.BackwardForward;
import org.audiveris.proxymusic.Barline;
import org.audiveris.proxymusic.Direction;
import org.audiveris.proxymusic.Empty;
import org.audiveris.proxymusic.Ending;
import org.audiveris.proxymusic.Note;
import org.audiveris.proxymusic.Offset;
import org.audiveris.proxymusic.PartList;
import org.audiveris.proxymusic.PartName;
import org.audiveris.proxymusic.Pitch;
import org.audiveris.proxymusic.Repeat;
import org.audiveris.proxymusic.Rest;
import org.audiveris.proxymusic.RightLeftMiddle;
import org.audiveris.proxymusic.ScorePart;
import org.audiveris.proxymusic.ScorePartwise;
import org.audiveris.proxymusic.Sound;
import org.audiveris.proxymusic.StartStop;
import org.audiveris.proxymusic.StartStopDiscontinue;
import org.audiveris.proxymusic.Step;
import org.audiveris.proxymusic.Tie;
import org.audiveris.proxymusic.Transpose;
import org.audiveris.proxymusic.YesNo;
import org.audiveris.proxymusic.util.Marshalling;
import org.junit.Test;

import javax.sound.midi.*;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;

/**
 * Executable serialization audit, deliberately independent of image recognition.
 * Every fixture writes a real .mid, reads it back, and compares literal reference
 * pitch/onset/offset events. JSON and the input MusicXML are retained for inspection.
 */
public class MidiExporterAccuracyTest
{
    private record Case(String name, ScorePartwise score, List<String> expected) {}

    @Test
    public void auditWrittenMidiAgainstReferenceEvents () throws Exception
    {
        String phase = System.getenv().getOrDefault("NOTELITE_MIDI_AUDIT_PHASE", "current");
        Path dir = Path.of("build", "midi-accuracy", phase);
        Files.createDirectories(dir);
        int passed = 0, expectedCount = 0, actualCount = 0, matchedCount = 0;
        List<String> reports = new ArrayList<>();
        List<String> failures = new ArrayList<>();
        for (Case fixture : cases()) {
            Path midi = dir.resolve(fixture.name + ".mid");
            try (var xml = Files.newOutputStream(dir.resolve(fixture.name + ".musicxml"))) {
                Marshalling.marshal(fixture.score, xml, false, 2);
            }
            MidiExporter.write(fixture.score, midi);
            Sequence sequence = MidiSystem.getSequence(midi.toFile());
            List<String> actual = events(sequence);
            List<String> expected = new ArrayList<>(fixture.expected);
            Collections.sort(expected);
            List<String> unmatched = new ArrayList<>(actual);
            int matched = 0;
            for (String event : expected) if (unmatched.remove(event)) matched++;
            boolean ok = expected.equals(actual);
            if (ok) passed++; else failures.add(fixture.name);
            expectedCount += expected.size(); actualCount += actual.size(); matchedCount += matched;
            reports.add("{\"name\":\"" + fixture.name + "\",\"passed\":" + ok
                    + ",\"resolution\":" + sequence.getResolution()
                    + ",\"matchedEvents\":" + matched + ",\"expected\":" + json(expected)
                    + ",\"actual\":" + json(actual) + "}");
        }
        String report = "{\"scope\":\"MusicXML model to written MIDI; NOT OMR accuracy\","
                + "\"metric\":\"Exact multiset match of pitch, channel and onset/offset in quarter-note beats; tempo in microseconds per quarter\","
                + "\"fixtureCount\":" + reports.size() + ",\"passedFixtures\":" + passed
                + ",\"expectedEvents\":" + expectedCount + ",\"actualEvents\":" + actualCount
                + ",\"matchedEvents\":" + matchedCount + ",\"cases\":["
                + String.join(",\n", reports) + "]}";
        Files.writeString(dir.resolve("results.json"), report, StandardCharsets.UTF_8);
        System.out.println("MIDI audit: " + passed + "/" + reports.size() + " fixtures; "
                + matchedCount + "/" + expectedCount + " reference events. Evidence: " + dir);
        assertEquals("Failing MIDI fixtures: " + failures, reports.size(), passed);
    }

    private static List<Case> cases ()
    {
        List<Case> out = new ArrayList<>();
        ScorePartwise s = score(); var p = part(s); var m = measure(p, 480);
        String[] steps = {"C", "D", "E", "F", "G", "A", "B", "C"};
        int[] pitches = {60, 62, 64, 65, 67, 69, 71, 72};
        List<String> e = new ArrayList<>();
        for (int i = 0; i < steps.length; i++) {
            m.getNoteOrBackupOrForward().add(note(steps[i], i == 7 ? 5 : 4, 480));
            expect(e, 0, pitches[i], i, i + 1);
        }
        out.add(new Case("diatonic_scale", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        Note flat = note("B", 3, 720); flat.getPitch().setAlter(bd(-1));
        Note sharp = note("F", 4, 240); sharp.getPitch().setAlter(bd(1));
        Note doubleSharp = note("C", 5, 480); doubleSharp.getPitch().setAlter(bd(2));
        m.getNoteOrBackupOrForward().addAll(List.of(flat, sharp, doubleSharp));
        expect(e, 0, 58, 0, 1.5); expect(e, 0, 66, 1.5, 2); expect(e, 0, 74, 2, 3);
        out.add(new Case("accidentals_dotted_rhythm", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        Note rest = new Note(); rest.setRest(new Rest()); rest.setDuration(bd(240));
        Note c = note("C", 4, 480), g = note("G", 4, 480); g.setChord(new Empty());
        m.getNoteOrBackupOrForward().addAll(List.of(rest, c, g, note("D", 4, 240)));
        expect(e, 0, 60, .5, 1.5); expect(e, 0, 67, .5, 1.5); expect(e, 0, 62, 1.5, 2);
        out.add(new Case("rest_chord", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            Note n = note("A", 4, 480);
            if (i > 0) tie(n, StartStop.STOP);
            if (i < 2) tie(n, StartStop.START);
            m.getNoteOrBackupOrForward().add(n);
        }
        expect(e, 0, 69, 0, 3); out.add(new Case("three_note_tie", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        m.getNoteOrBackupOrForward().add(note("C", 4, 480));
        m = measure(p, 960); m.getNoteOrBackupOrForward().add(note("D", 4, 960));
        m = measure(p, 240); m.getNoteOrBackupOrForward().add(note("E", 4, 120));
        expect(e, 0, 60, 0, 1); expect(e, 0, 62, 1, 2); expect(e, 0, 64, 2, 2.5);
        out.add(new Case("divisions_change", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        m.getNoteOrBackupOrForward().add(note("C", 4, 480));
        p = part(s); m = measure(p, 240); m.getNoteOrBackupOrForward().add(note("G", 3, 240));
        expect(e, 0, 60, 0, 1); expect(e, 1, 55, 0, 1);
        out.add(new Case("per_part_divisions", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        Note upper = note("C", 5, 1920); upper.setVoice("1");
        Note lower = note("G", 3, 480); lower.setVoice("2");
        Backup backup = new Backup(); backup.setDuration(bd(1920));
        m.getNoteOrBackupOrForward().addAll(List.of(upper, backup, lower));
        m = measure(p, 480); m.getNoteOrBackupOrForward().add(note("D", 5, 480));
        expect(e, 0, 72, 0, 4); expect(e, 0, 55, 0, 1); expect(e, 0, 74, 4, 5);
        out.add(new Case("polyphonic_measure_boundary", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        Note a = note("C", 4, 480); a.setVoice("1"); tie(a, StartStop.START);
        Note b = note("C", 4, 480); b.setVoice("1"); tie(b, StartStop.STOP);
        Note d = note("C", 4, 240); d.setVoice("2"); tie(d, StartStop.START);
        Note f = note("C", 4, 240); f.setVoice("2"); tie(f, StartStop.STOP);
        backup = new Backup(); backup.setDuration(bd(480));
        m.getNoteOrBackupOrForward().addAll(List.of(a, backup, d));
        m = measure(p, 480); backup = new Backup(); backup.setDuration(bd(480));
        m.getNoteOrBackupOrForward().addAll(List.of(b, backup, f));
        expect(e, 0, 60, 0, 2); expect(e, 0, 60, 0, 1.5);
        out.add(new Case("independent_unison_ties", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        transpose(m, -2, 0, null); m.getNoteOrBackupOrForward().add(note("C", 4, 480));
        m = measure(p, 480); m.getNoteOrBackupOrForward().add(note("E", 4, 480));
        expect(e, 0, 58, 0, 1); expect(e, 0, 62, 1, 2);
        out.add(new Case("bb_instrument_transpose", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        transpose(m, 0, -1, 2);
        a = note("C", 4, 480); a.setStaff(BigInteger.ONE);
        b = note("C", 4, 480); b.setStaff(BigInteger.TWO); b.setChord(new Empty());
        m.getNoteOrBackupOrForward().addAll(List.of(a,b));
        expect(e, 0, 60, 0, 1); expect(e, 0, 48, 0, 1);
        out.add(new Case("staff_octave_transpose", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        repeat(m, BackwardForward.FORWARD, null); m.getNoteOrBackupOrForward().add(note("C", 4, 480));
        m = measure(p, 480); m.getNoteOrBackupOrForward().add(note("D", 4, 480)); repeat(m, BackwardForward.BACKWARD, null);
        for (int i = 0; i < 4; i++) expect(e, 0, i % 2 == 0 ? 60 : 62, i, i + 1);
        out.add(new Case("simple_repeat", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        m.getNoteOrBackupOrForward().add(note("E", 4, 480)); repeat(m, BackwardForward.BACKWARD, 3);
        for (int i = 0; i < 3; i++) expect(e, 0, 64, i, i + 1);
        out.add(new Case("implicit_repeat_three_passes", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        repeat(m, BackwardForward.FORWARD, null); m.getNoteOrBackupOrForward().add(note("C", 4, 480));
        m = measure(p, 480); ending(m, "1", StartStopDiscontinue.START);
        m.getNoteOrBackupOrForward().add(note("D", 4, 480)); ending(m, "1", StartStopDiscontinue.STOP); repeat(m, BackwardForward.BACKWARD, null);
        m = measure(p, 480); ending(m, "2", StartStopDiscontinue.START);
        m.getNoteOrBackupOrForward().add(note("E", 4, 480)); ending(m, "2", StartStopDiscontinue.STOP);
        expect(e, 0, 60, 0, 1); expect(e, 0, 62, 1, 2); expect(e, 0, 60, 2, 3); expect(e, 0, 64, 3, 4);
        out.add(new Case("first_second_endings", s, e));

        s = score(); p = part(s); m = measure(p, 480); e = new ArrayList<>();
        Direction direction = new Direction(); Sound sound = new Sound(); sound.setTempo(new BigDecimal("72.5"));
        direction.setSound(sound); Offset offset = new Offset(); offset.setValue(bd(240)); offset.setSound(YesNo.YES); direction.setOffset(offset);
        m.getNoteOrBackupOrForward().addAll(List.of(direction, note("A", 4, 480)));
        expect(e, 0, 69, 0, 1); e.add("tempo:827586@0.5");
        out.add(new Case("fractional_tempo_with_offset", s, e));

        s = score(); p = part(s); m = measure(p, 3); e = new ArrayList<>();
        for (int i = 0; i < 3; i++) m.getNoteOrBackupOrForward().add(note("C", 4, 1));
        expect(e, 0, 60, 0, 1.0/3); expect(e, 0, 60, 1.0/3, 2.0/3); expect(e, 0, 60, 2.0/3, 1);
        out.add(new Case("triplet_durations", s, e));
        return out;
    }

    private static ScorePartwise score () { return new ScorePartwise(); }
    private static ScorePartwise.Part part (ScorePartwise s) {
        var p = new ScorePartwise.Part(); ScorePart id = new ScorePart(); id.setId("P" + (s.getPart().size() + 1));
        PartName name = new PartName(); name.setValue(id.getId()); id.setPartName(name);
        if (s.getPartList() == null) s.setPartList(new PartList());
        s.getPartList().getPartGroupOrScorePart().add(id); p.setId(id); s.getPart().add(p); return p;
    }
    private static ScorePartwise.Part.Measure measure (ScorePartwise.Part p, int divisions) {
        var m = new ScorePartwise.Part.Measure(); m.setNumber("" + (p.getMeasure().size() + 1));
        Attributes a = new Attributes(); a.setDivisions(bd(divisions)); m.getNoteOrBackupOrForward().add(a); p.getMeasure().add(m); return m;
    }
    private static Note note (String step, int octave, int duration) {
        Note n = new Note(); Pitch p = new Pitch(); p.setStep(Step.fromValue(step)); p.setOctave(octave);
        n.setPitch(p); n.setDuration(bd(duration)); return n;
    }
    private static BigDecimal bd (int n) { return BigDecimal.valueOf(n); }
    private static void tie (Note n, StartStop type) { Tie t = new Tie(); t.setType(type); n.getTie().add(t); }
    private static void transpose (ScorePartwise.Part.Measure m, int chromatic, int octave, Integer staff) {
        Transpose t = new Transpose(); t.setChromatic(bd(chromatic)); t.setOctaveChange(BigInteger.valueOf(octave));
        if (staff != null) t.setNumber(BigInteger.valueOf(staff));
        ((Attributes) m.getNoteOrBackupOrForward().get(0)).getTranspose().add(t);
    }
    private static void repeat (ScorePartwise.Part.Measure m, BackwardForward direction, Integer times) {
        Barline b = new Barline(); Repeat r = new Repeat(); r.setDirection(direction);
        b.setLocation(direction == BackwardForward.FORWARD ? RightLeftMiddle.LEFT : RightLeftMiddle.RIGHT);
        if (times != null) r.setTimes(BigInteger.valueOf(times)); b.setRepeat(r); m.getNoteOrBackupOrForward().add(b);
    }
    private static void ending (ScorePartwise.Part.Measure m, String number, StartStopDiscontinue type) {
        Barline b = new Barline(); Ending e = new Ending(); e.setNumber(number); e.setType(type);
        b.setLocation(type == StartStopDiscontinue.START ? RightLeftMiddle.LEFT : RightLeftMiddle.RIGHT);
        b.setEnding(e); m.getNoteOrBackupOrForward().add(b);
    }
    private static String beat (double n) { return String.format(java.util.Locale.ROOT, "%.6f", n).replaceAll("0+$", "").replaceAll("\\.$", ""); }
    private static void expect (List<String> e, int channel, int pitch, double on, double off) {
        e.add("on:" + channel + ":" + pitch + "@" + beat(on)); e.add("off:" + channel + ":" + pitch + "@" + beat(off));
    }
    private static List<String> events (Sequence s) {
        List<String> events = new ArrayList<>();
        for (Track track : s.getTracks()) for (int i = 0; i < track.size(); i++) {
            MidiEvent ev = track.get(i); MidiMessage msg = ev.getMessage(); String tick = beat((double) ev.getTick() / s.getResolution());
            if (msg instanceof ShortMessage sm) {
                if (sm.getCommand() == ShortMessage.NOTE_ON && sm.getData2() > 0) events.add("on:" + sm.getChannel() + ":" + sm.getData1() + "@" + tick);
                else if (sm.getCommand() == ShortMessage.NOTE_OFF || sm.getCommand() == ShortMessage.NOTE_ON && sm.getData2() == 0) events.add("off:" + sm.getChannel() + ":" + sm.getData1() + "@" + tick);
            } else if (msg instanceof MetaMessage mm && mm.getType() == 0x51) {
                byte[] bytes = mm.getData(); int tempo = ((bytes[0] & 255) << 16) | ((bytes[1] & 255) << 8) | (bytes[2] & 255);
                events.add("tempo:" + tempo + "@" + tick);
            }
        }
        Collections.sort(events); return events;
    }
    private static String json (List<String> items) { return "[\"" + String.join("\",\"", items) + "\"]"; }
}
