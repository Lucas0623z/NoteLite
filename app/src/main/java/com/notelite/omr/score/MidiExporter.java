//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    M i d i E x p o r t e r                                     //
//                                                                                                //
//------------------------------------------------------------------------------------------------//
// <editor-fold defaultstate="collapsed" desc="hdr">
//
//  Copyright © NoteLite 2026. All rights reserved.
//
//  This program is free software: you can redistribute it and/or modify it under the terms of the
//  GNU Affero General Public License as published by the Free Software Foundation, either version
//  3 of the License, or (at your option) any later version.
//
//  This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
//  without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
//  See the GNU Affero General Public License for more details.
//
//  You should have received a copy of the GNU Affero General Public License along with this
//  program.  If not, see <http://www.gnu.org/licenses/>.
//------------------------------------------------------------------------------------------------//
// </editor-fold>
package com.notelite.omr.score;

import org.audiveris.proxymusic.Attributes;
import org.audiveris.proxymusic.Backup;
import org.audiveris.proxymusic.Direction;
import org.audiveris.proxymusic.Forward;
import org.audiveris.proxymusic.MidiInstrument;
import org.audiveris.proxymusic.Note;
import org.audiveris.proxymusic.Pitch;
import org.audiveris.proxymusic.ScorePart;
import org.audiveris.proxymusic.ScorePartwise;
import org.audiveris.proxymusic.Sound;
import org.audiveris.proxymusic.StartStop;
import org.audiveris.proxymusic.Step;
import org.audiveris.proxymusic.Tie;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.sound.midi.InvalidMidiDataException;
import javax.sound.midi.MetaMessage;
import javax.sound.midi.MidiEvent;
import javax.sound.midi.MidiSystem;
import javax.sound.midi.Sequence;
import javax.sound.midi.ShortMessage;
import javax.sound.midi.Track;
import java.io.IOException;
import java.nio.file.Path;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

/**
 * Class <code>MidiExporter</code> converts a populated proxymusic
 * {@link ScorePartwise} model into a Standard MIDI File (Type 1) using
 * the JDK-bundled {@code javax.sound.midi}.
 * <p>
 * The exporter reuses Stage A of the MusicXML pipeline
 * ({@link PartwiseBuilder#build(Score)}) and only replaces the serialization
 * stage. See {@code MIDI_EXPORT_PLAN.md} §4 for the full call chain.
 * <p>
 * First-version coverage: pitched notes, rests, chords, tied notes,
 * tempo directions, multi-part with per-part track and channel routing.
 * Out of scope (see plan §2): velocity dynamics, drum mapping, transpose,
 * repeats expansion, ornaments, articulation timing.
 *
 * @author NoteLite Contributors
 */
public class MidiExporter
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(MidiExporter.class);

    /** Fixed velocity for first version. */
    static final int DEFAULT_VELOCITY = 80;

    /** PPQ used when no Attributes.divisions can be discovered. */
    static final int DEFAULT_PPQ = 480;

    /** Tick length used for grace notes (no XML duration). */
    static final int GRACE_TICKS = 30;

    /** ABCDEFG → semitone offset within the octave. Verified against proxymusic Step enum. */
    private static final Map<Step, Integer> STEP_SEMITONE;

    static {
        STEP_SEMITONE = new EnumMap<>(Step.class);
        STEP_SEMITONE.put(Step.C, 0);
        STEP_SEMITONE.put(Step.D, 2);
        STEP_SEMITONE.put(Step.E, 4);
        STEP_SEMITONE.put(Step.F, 5);
        STEP_SEMITONE.put(Step.G, 7);
        STEP_SEMITONE.put(Step.A, 9);
        STEP_SEMITONE.put(Step.B, 11);
    }

    //~ Instance fields ----------------------------------------------------------------------------

    private final Score score;

    //~ Constructors -------------------------------------------------------------------------------

    public MidiExporter (Score score)
    {
        this.score = Objects.requireNonNull(score, "score");
    }

    //~ Methods ------------------------------------------------------------------------------------

    /**
     * Build the proxymusic model for the bound score and write a MIDI file.
     */
    public void export (Path path)
            throws IOException, InvalidMidiDataException, Exception
    {
        ScorePartwise sp = PartwiseBuilder.build(score);
        write(sp, path);
    }

    /**
     * Convert a fully built {@link ScorePartwise} model to a MIDI file.
     * Exposed at package level so unit tests can drive the converter with a
     * hand-built model and skip the OMR-side machinery.
     */
    static void write (ScorePartwise sp, Path path)
            throws IOException, InvalidMidiDataException
    {
        Sequence sequence = buildSequence(sp);
        MidiSystem.write(sequence, 1, path.toFile());
    }

    /**
     * Build a Type-1 MIDI Sequence. Track 0 holds global meta (tempo, copyright);
     * tracks 1..N each carry one Part.
     */
    static Sequence buildSequence (ScorePartwise sp)
            throws InvalidMidiDataException
    {
        int ppq = extractFirstDivisions(sp);
        Sequence sequence = new Sequence(Sequence.PPQ, ppq);

        Track meta = sequence.createTrack();
        addCopyrightMeta(meta, "NoteLite");

        int partIndex = 0;
        for (ScorePartwise.Part part : sp.getPart()) {
            Track track = sequence.createTrack();

            int[] cp = extractChannelProgram(part, partIndex);
            int channel = cp[0];
            int program = cp[1];

            ShortMessage pc = new ShortMessage();
            pc.setMessage(ShortMessage.PROGRAM_CHANGE, channel, program, 0);
            track.add(new MidiEvent(pc, 0));

            walkPart(part, track, meta, channel);
            partIndex++;
        }

        return sequence;
    }

    private static void walkPart (ScorePartwise.Part part,
                                  Track track,
                                  Track meta,
                                  int channel)
            throws InvalidMidiDataException
    {
        long currentTick = 0;
        long lastChordTick = 0;
        Map<Integer, Long> pendingNoteOff = new HashMap<>();

        for (ScorePartwise.Part.Measure measure : part.getMeasure()) {
            for (Object item : measure.getNoteOrBackupOrForward()) {
                if (item instanceof Note) {
                    Note note = (Note) item;
                    handleNote(note, track, channel, currentTick, lastChordTick,
                               pendingNoteOff);

                    if (note.getChord() == null) {
                        long dur = (note.getDuration() != null)
                                ? note.getDuration().longValue() : 0;
                        lastChordTick = currentTick;
                        currentTick += dur;
                    }
                } else if (item instanceof Backup) {
                    long dur = ((Backup) item).getDuration().longValue();
                    currentTick -= dur;
                } else if (item instanceof Forward) {
                    long dur = ((Forward) item).getDuration().longValue();
                    currentTick += dur;
                } else if (item instanceof Direction) {
                    handleDirection((Direction) item, meta, currentTick);
                }
                // Attributes / Barline / Print → first version: no event needed
            }
        }

        // Safety: any remaining open ties get closed at the very end.
        for (Map.Entry<Integer, Long> e : pendingNoteOff.entrySet()) {
            addNoteOff(track, channel, e.getKey(), e.getValue());
        }
    }

    private static void handleNote (Note note,
                                    Track track,
                                    int channel,
                                    long currentTick,
                                    long lastChordTick,
                                    Map<Integer, Long> pendingNoteOff)
            throws InvalidMidiDataException
    {
        if (note.getRest() != null) {
            return;
        }

        Pitch pitch = note.getPitch();
        if (pitch == null) {
            // unpitched (drum) — out of scope for first version
            return;
        }

        long onsetTick = (note.getChord() != null) ? lastChordTick : currentTick;

        long duration = (note.getDuration() != null) ? note.getDuration().longValue() : 0;
        if (note.getGrace() != null) {
            duration = GRACE_TICKS;
        }

        int midiPitch = computeMidiPitch(pitch);

        boolean tieStart = false;
        boolean tieStop = false;
        for (Tie tie : note.getTie()) {
            if (tie.getType() == StartStop.START) tieStart = true;
            if (tie.getType() == StartStop.STOP) tieStop = true;
        }

        if (tieStop && pendingNoteOff.containsKey(midiPitch)) {
            long newOff = onsetTick + duration;
            if (tieStart) {
                pendingNoteOff.put(midiPitch, newOff);
            } else {
                addNoteOff(track, channel, midiPitch, newOff);
                pendingNoteOff.remove(midiPitch);
            }
        } else {
            addNoteOn(track, channel, midiPitch, onsetTick);
            if (tieStart) {
                pendingNoteOff.put(midiPitch, onsetTick + duration);
            } else {
                addNoteOff(track, channel, midiPitch, onsetTick + duration);
            }
        }
    }

    private static void handleDirection (Direction direction, Track meta, long tick)
            throws InvalidMidiDataException
    {
        Sound sound = direction.getSound();
        if (sound == null || sound.getTempo() == null) {
            return;
        }
        int bpm = sound.getTempo().intValue();
        if (bpm <= 0) {
            return;
        }
        int microsecondsPerQuarter = 60_000_000 / bpm;
        byte[] data = {
            (byte) ((microsecondsPerQuarter >> 16) & 0xFF),
            (byte) ((microsecondsPerQuarter >> 8) & 0xFF),
            (byte) (microsecondsPerQuarter & 0xFF)
        };
        MetaMessage tempo = new MetaMessage();
        tempo.setMessage(0x51, data, 3);
        meta.add(new MidiEvent(tempo, tick));
    }

    //~ Helpers ------------------------------------------------------------------------------------

    static int computeMidiPitch (Pitch pitch)
    {
        Integer semi = STEP_SEMITONE.get(pitch.getStep());
        if (semi == null) {
            throw new IllegalStateException("Unknown step: " + pitch.getStep());
        }
        int alter = (pitch.getAlter() != null) ? pitch.getAlter().intValue() : 0;
        return (pitch.getOctave() + 1) * 12 + semi + alter;
    }

    private static void addNoteOn (Track t, int channel, int pitch, long tick)
            throws InvalidMidiDataException
    {
        ShortMessage m = new ShortMessage();
        m.setMessage(ShortMessage.NOTE_ON, channel, pitch, DEFAULT_VELOCITY);
        t.add(new MidiEvent(m, tick));
    }

    private static void addNoteOff (Track t, int channel, int pitch, long tick)
            throws InvalidMidiDataException
    {
        ShortMessage m = new ShortMessage();
        m.setMessage(ShortMessage.NOTE_OFF, channel, pitch, 0);
        t.add(new MidiEvent(m, tick));
    }

    private static int extractFirstDivisions (ScorePartwise sp)
    {
        for (ScorePartwise.Part part : sp.getPart()) {
            for (ScorePartwise.Part.Measure m : part.getMeasure()) {
                for (Object item : m.getNoteOrBackupOrForward()) {
                    if (item instanceof Attributes) {
                        Attributes a = (Attributes) item;
                        if (a.getDivisions() != null) {
                            return a.getDivisions().intValue();
                        }
                    }
                }
            }
        }
        return DEFAULT_PPQ;
    }

    /**
     * Extract MIDI channel (0-based) and program (0-based) for the given Part,
     * preferring values from the linked ScorePart's MidiInstrument.
     * Falls back to round-robin channel and Acoustic Grand Piano (program 0).
     */
    private static int[] extractChannelProgram (ScorePartwise.Part part, int fallbackIndex)
    {
        int channel = fallbackIndex % 16;
        int program = 0;

        Object idRef = part.getId();
        if (idRef instanceof ScorePart) {
            ScorePart scorePart = (ScorePart) idRef;
            for (Object o : scorePart.getMidiDeviceAndMidiInstrument()) {
                if (o instanceof MidiInstrument) {
                    MidiInstrument mi = (MidiInstrument) o;
                    if (mi.getMidiChannel() != null) {
                        channel = Math.max(0, mi.getMidiChannel() - 1);
                    }
                    if (mi.getMidiProgram() != null) {
                        program = Math.max(0, mi.getMidiProgram() - 1);
                    }
                    break;
                }
            }
        }
        return new int[] {channel, program};
    }

    private static void addCopyrightMeta (Track meta, String text)
            throws InvalidMidiDataException
    {
        byte[] bytes = text.getBytes();
        MetaMessage m = new MetaMessage();
        m.setMessage(0x02, bytes, bytes.length);
        meta.add(new MidiEvent(m, 0));
    }
}
