/*
 * Copyright © NoteLite 2026. All rights reserved.
 * This software is released under the GNU Affero General Public License.
 */
package com.notelite.omr.score;

import org.audiveris.proxymusic.Attributes;
import org.audiveris.proxymusic.Empty;
import org.audiveris.proxymusic.MidiInstrument;
import org.audiveris.proxymusic.Note;
import org.audiveris.proxymusic.ObjectFactory;
import org.audiveris.proxymusic.PartList;
import org.audiveris.proxymusic.PartName;
import org.audiveris.proxymusic.Pitch;
import org.audiveris.proxymusic.Rest;
import org.audiveris.proxymusic.ScorePart;
import org.audiveris.proxymusic.ScorePartwise;
import org.audiveris.proxymusic.StartStop;
import org.audiveris.proxymusic.Step;
import org.audiveris.proxymusic.Tie;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import javax.sound.midi.MetaMessage;
import javax.sound.midi.MidiEvent;
import javax.sound.midi.MidiMessage;
import javax.sound.midi.MidiSystem;
import javax.sound.midi.Sequence;
import javax.sound.midi.ShortMessage;
import javax.sound.midi.Track;
import java.io.File;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * Stage 1 unit tests for {@link MidiExporter}: construct ScorePartwise
 * objects in memory with proxymusic's {@link ObjectFactory}, write a MIDI
 * file, then read it back via {@link MidiSystem#getSequence(File)} to
 * assert event timing/pitch.
 */
public class MidiExporterTest
{
    /** Standard PPQ used for all tests; one quarter note = 480 ticks. */
    private static final int PPQ = 480;

    private static final int QUARTER = 480;

    private ObjectFactory factory;

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    @Before
    public void setUp ()
    {
        factory = new ObjectFactory();
    }

    //--------//
    // Test 1 // single part, single quarter note (A4)
    //--------//
    @Test
    public void testSingleNote ()
            throws Exception
    {
        // First, sanity check: proxymusic Step enum order matches our pitch table.
        assertEquals("Step enum is alphabetical (A first)", 0, Step.A.ordinal());
        assertEquals("C is third", 2, Step.C.ordinal());

        ScorePartwise sp = newScore();
        ScorePartwise.Part part = addPart(sp, "P1", 1, 1); // channel 1, program 1
        ScorePartwise.Part.Measure m = addMeasure(part, "1", PPQ);
        m.getNoteOrBackupOrForward().add(pitchedNote("A", 4, QUARTER));

        File out = tmp.newFile("single.mid");
        MidiExporter.write(sp, out.toPath());

        Sequence seq = MidiSystem.getSequence(out);
        assertEquals("PPQ resolution preserved", PPQ, seq.getResolution());
        assertEquals("meta + 1 part track", 2, seq.getTracks().length);

        Track partTrack = seq.getTracks()[1];
        List<MidiEvent> noteOns = collectNoteOn(partTrack);
        List<MidiEvent> noteOffs = collectNoteOff(partTrack);
        assertEquals("exactly one NoteOn", 1, noteOns.size());
        assertEquals("exactly one NoteOff", 1, noteOffs.size());

        ShortMessage on = (ShortMessage) noteOns.get(0).getMessage();
        assertEquals("A4 = MIDI 69", 69, on.getData1());
        assertEquals("velocity 80", MidiExporter.DEFAULT_VELOCITY, on.getData2());
        assertEquals("channel 0 (proxymusic ch1 → javax ch0)", 0, on.getChannel());
        assertEquals("NoteOn at tick 0", 0L, noteOns.get(0).getTick());
        assertEquals("NoteOff at tick 480", (long) QUARTER, noteOffs.get(0).getTick());
    }

    //--------//
    // Test 2 // chord: A4 + C5 + E5 sharing onset
    //--------//
    @Test
    public void testChord ()
            throws Exception
    {
        ScorePartwise sp = newScore();
        ScorePartwise.Part part = addPart(sp, "P1", 1, 1);
        ScorePartwise.Part.Measure m = addMeasure(part, "1", PPQ);

        m.getNoteOrBackupOrForward().add(pitchedNote("A", 4, QUARTER));         // first
        m.getNoteOrBackupOrForward().add(chordNote("C", 5, QUARTER));           // chord
        m.getNoteOrBackupOrForward().add(chordNote("E", 5, QUARTER));           // chord

        File out = tmp.newFile("chord.mid");
        MidiExporter.write(sp, out.toPath());

        Sequence seq = MidiSystem.getSequence(out);
        Track t = seq.getTracks()[1];
        List<MidiEvent> ons = collectNoteOn(t);
        List<MidiEvent> offs = collectNoteOff(t);

        assertEquals("3 NoteOn for triad", 3, ons.size());
        assertEquals("3 NoteOff for triad", 3, offs.size());

        for (MidiEvent ev : ons) {
            assertEquals("all chord NoteOn share tick 0", 0L, ev.getTick());
        }
        for (MidiEvent ev : offs) {
            assertEquals("all chord NoteOff share tick 480", (long) QUARTER, ev.getTick());
        }

        List<Integer> pitches = new ArrayList<>();
        for (MidiEvent ev : ons) {
            pitches.add(((ShortMessage) ev.getMessage()).getData1());
        }
        assertTrue("contains A4", pitches.contains(69));
        assertTrue("contains C5", pitches.contains(72));
        assertTrue("contains E5", pitches.contains(76));
    }

    //--------//
    // Test 3 // tied A4 (start → stop): single NoteOn at 0, single NoteOff at 960
    //--------//
    @Test
    public void testTiedNotes ()
            throws Exception
    {
        ScorePartwise sp = newScore();
        ScorePartwise.Part part = addPart(sp, "P1", 1, 1);
        ScorePartwise.Part.Measure m = addMeasure(part, "1", PPQ);

        Note n1 = pitchedNote("A", 4, QUARTER);
        Tie t1 = factory.createTie();
        t1.setType(StartStop.START);
        n1.getTie().add(t1);

        Note n2 = pitchedNote("A", 4, QUARTER);
        Tie t2 = factory.createTie();
        t2.setType(StartStop.STOP);
        n2.getTie().add(t2);

        m.getNoteOrBackupOrForward().add(n1);
        m.getNoteOrBackupOrForward().add(n2);

        File out = tmp.newFile("tied.mid");
        MidiExporter.write(sp, out.toPath());

        Sequence seq = MidiSystem.getSequence(out);
        Track t = seq.getTracks()[1];
        List<MidiEvent> ons = collectNoteOn(t);
        List<MidiEvent> offs = collectNoteOff(t);

        assertEquals("tie → only one NoteOn", 1, ons.size());
        assertEquals("tie → only one NoteOff", 1, offs.size());
        assertEquals("NoteOn at 0", 0L, ons.get(0).getTick());
        assertEquals("NoteOff after combined duration", (long) (QUARTER * 2),
                     offs.get(0).getTick());
    }

    //--------//
    // Test 4 // rest then A4: NoteOn must land at tick 480
    //--------//
    @Test
    public void testRestAdvancesTime ()
            throws Exception
    {
        ScorePartwise sp = newScore();
        ScorePartwise.Part part = addPart(sp, "P1", 1, 1);
        ScorePartwise.Part.Measure m = addMeasure(part, "1", PPQ);

        m.getNoteOrBackupOrForward().add(restNote(QUARTER));
        m.getNoteOrBackupOrForward().add(pitchedNote("A", 4, QUARTER));

        File out = tmp.newFile("rest.mid");
        MidiExporter.write(sp, out.toPath());

        Sequence seq = MidiSystem.getSequence(out);
        Track t = seq.getTracks()[1];
        List<MidiEvent> ons = collectNoteOn(t);
        List<MidiEvent> offs = collectNoteOff(t);

        assertEquals("only the pitched note emits NoteOn", 1, ons.size());
        assertEquals("rest pushed onset to second beat", (long) QUARTER,
                     ons.get(0).getTick());
        assertEquals("NoteOff one quarter later", (long) (QUARTER * 2),
                     offs.get(0).getTick());
    }

    //--------//
    // Test 5 // two parts → two tracks, distinct channels from MidiInstrument
    //--------//
    @Test
    public void testMultiPart ()
            throws Exception
    {
        ScorePartwise sp = newScore();
        ScorePartwise.Part p1 = addPart(sp, "P1", 1, 1);   // channel 1 → javax 0
        ScorePartwise.Part p2 = addPart(sp, "P2", 2, 41);  // channel 2 → javax 1, program 41

        ScorePartwise.Part.Measure m1 = addMeasure(p1, "1", PPQ);
        m1.getNoteOrBackupOrForward().add(pitchedNote("C", 4, QUARTER));

        ScorePartwise.Part.Measure m2 = addMeasure(p2, "1", PPQ);
        m2.getNoteOrBackupOrForward().add(pitchedNote("G", 4, QUARTER));

        File out = tmp.newFile("multi.mid");
        MidiExporter.write(sp, out.toPath());

        Sequence seq = MidiSystem.getSequence(out);
        assertEquals("meta + 2 part tracks", 3, seq.getTracks().length);

        ShortMessage on1 = (ShortMessage) collectNoteOn(seq.getTracks()[1]).get(0).getMessage();
        ShortMessage on2 = (ShortMessage) collectNoteOn(seq.getTracks()[2]).get(0).getMessage();

        assertEquals("part 1 on channel 0", 0, on1.getChannel());
        assertEquals("part 2 on channel 1", 1, on2.getChannel());
        assertEquals("part 1 plays C4 (60)", 60, on1.getData1());
        assertEquals("part 2 plays G4 (67)", 67, on2.getData1());

        // ProgramChange should reflect MidiInstrument.midiProgram - 1.
        ShortMessage pc2 = findProgramChange(seq.getTracks()[2]);
        assertNotNull("part 2 has ProgramChange", pc2);
        assertEquals("program 41 → MIDI data 40", 40, pc2.getData1());
    }

    //~ Test fixture helpers -----------------------------------------------------------------------

    private ScorePartwise newScore ()
    {
        ScorePartwise sp = factory.createScorePartwise();
        PartList pl = factory.createPartList();
        sp.setPartList(pl);
        return sp;
    }

    private ScorePartwise.Part addPart (ScorePartwise sp,
                                        String partId,
                                        int midiChannel,
                                        int midiProgram)
    {
        ScorePart sPart = factory.createScorePart();
        sPart.setId(partId);
        PartName pn = factory.createPartName();
        pn.setValue(partId);
        sPart.setPartName(pn);

        MidiInstrument mi = factory.createMidiInstrument();
        mi.setId(sPart);
        mi.setMidiChannel(midiChannel);
        mi.setMidiProgram(midiProgram);
        sPart.getMidiDeviceAndMidiInstrument().add(mi);

        sp.getPartList().getPartGroupOrScorePart().add(sPart);

        ScorePartwise.Part part = factory.createScorePartwisePart();
        part.setId(sPart);
        sp.getPart().add(part);
        return part;
    }

    private ScorePartwise.Part.Measure addMeasure (ScorePartwise.Part part,
                                                   String number,
                                                   int divisions)
    {
        ScorePartwise.Part.Measure m = factory.createScorePartwisePartMeasure();
        m.setNumber(number);
        Attributes a = factory.createAttributes();
        a.setDivisions(BigDecimal.valueOf(divisions));
        m.getNoteOrBackupOrForward().add(a);
        part.getMeasure().add(m);
        return m;
    }

    private Note pitchedNote (String step, int octave, int duration)
    {
        Note note = factory.createNote();
        Pitch pitch = factory.createPitch();
        pitch.setStep(Step.fromValue(step));
        pitch.setOctave(octave);
        note.setPitch(pitch);
        note.setDuration(BigDecimal.valueOf(duration));
        return note;
    }

    private Note chordNote (String step, int octave, int duration)
    {
        Note note = pitchedNote(step, octave, duration);
        note.setChord(new Empty());
        return note;
    }

    private Note restNote (int duration)
    {
        Note note = factory.createNote();
        Rest rest = factory.createRest();
        note.setRest(rest);
        note.setDuration(BigDecimal.valueOf(duration));
        return note;
    }

    private static List<MidiEvent> collectNoteOn (Track t)
    {
        List<MidiEvent> out = new ArrayList<>();
        for (int i = 0; i < t.size(); i++) {
            MidiEvent ev = t.get(i);
            MidiMessage msg = ev.getMessage();
            if (msg instanceof ShortMessage) {
                ShortMessage sm = (ShortMessage) msg;
                if (sm.getCommand() == ShortMessage.NOTE_ON && sm.getData2() > 0) {
                    out.add(ev);
                }
            }
        }
        return out;
    }

    private static List<MidiEvent> collectNoteOff (Track t)
    {
        List<MidiEvent> out = new ArrayList<>();
        for (int i = 0; i < t.size(); i++) {
            MidiEvent ev = t.get(i);
            MidiMessage msg = ev.getMessage();
            if (msg instanceof ShortMessage) {
                ShortMessage sm = (ShortMessage) msg;
                int cmd = sm.getCommand();
                // Some writers convert NoteOff to NoteOn with velocity 0.
                if (cmd == ShortMessage.NOTE_OFF
                    || (cmd == ShortMessage.NOTE_ON && sm.getData2() == 0)) {
                    out.add(ev);
                }
            }
        }
        return out;
    }

    private static ShortMessage findProgramChange (Track t)
    {
        for (int i = 0; i < t.size(); i++) {
            MidiMessage msg = t.get(i).getMessage();
            if (msg instanceof ShortMessage) {
                ShortMessage sm = (ShortMessage) msg;
                if (sm.getCommand() == ShortMessage.PROGRAM_CHANGE) {
                    return sm;
                }
            }
        }
        return null;
    }

    @SuppressWarnings("unused")
    private static MetaMessage findMeta (Track t, int type)
    {
        for (int i = 0; i < t.size(); i++) {
            MidiMessage msg = t.get(i).getMessage();
            if (msg instanceof MetaMessage && ((MetaMessage) msg).getType() == type) {
                return (MetaMessage) msg;
            }
        }
        return null;
    }
}
