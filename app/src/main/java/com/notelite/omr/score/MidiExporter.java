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
import org.audiveris.proxymusic.BackwardForward;
import org.audiveris.proxymusic.Barline;
import org.audiveris.proxymusic.Direction;
import org.audiveris.proxymusic.Ending;
import org.audiveris.proxymusic.Forward;
import org.audiveris.proxymusic.Key;
import org.audiveris.proxymusic.MidiInstrument;
import org.audiveris.proxymusic.Note;
import org.audiveris.proxymusic.Pitch;
import org.audiveris.proxymusic.Repeat;
import org.audiveris.proxymusic.ScorePart;
import org.audiveris.proxymusic.ScorePartwise;
import org.audiveris.proxymusic.Sound;
import org.audiveris.proxymusic.StartStop;
import org.audiveris.proxymusic.StartStopDiscontinue;
import org.audiveris.proxymusic.Step;
import org.audiveris.proxymusic.Tie;
import org.audiveris.proxymusic.Time;
import org.audiveris.proxymusic.Transpose;
import org.audiveris.proxymusic.YesNo;

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
import java.math.BigDecimal;
import java.math.BigInteger;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Deque;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Class <code>MidiExporter</code> converts a populated proxymusic
 * {@link ScorePartwise} model into a Standard MIDI File (Type 1) using
 * the JDK-bundled {@code javax.sound.midi}.
 * <p>
 * The exporter reuses Stage A of the MusicXML pipeline
 * ({@link PartwiseBuilder#build(Score)}) and only replaces the serialization
 * stage. See {@code MIDI_EXPORT_PLAN.md} §4 for the full call chain.
 * <p>
 * Handles pitched notes, rests, chords, voice-specific ties, tempo directions,
 * divisions changes, instrument transposition, and barline repeats with numbered endings.
 * Velocity dynamics, drum mapping, D.C./D.S./coda jumps, ornaments and expressive
 * articulation timing are not interpreted.
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
        int ppq = extractResolution(sp);
        Sequence sequence = new Sequence(Sequence.PPQ, ppq);

        Track meta = sequence.createTrack();
        addCopyrightMeta(meta, "NoteLite");

        List<List<MeasureData>> parts = new ArrayList<>();
        List<Long> measureLengths = new ArrayList<>();
        Map<Integer, Long> notatedLengths = new HashMap<>();
        for (ScorePartwise.Part part : sp.getPart()) {
            List<MeasureData> measures = readPart(part, ppq);
            parts.add(measures);
            for (int i = 0; i < measures.size(); i++) {
                if (i == measureLengths.size()) measureLengths.add(0L);
                measureLengths.set(i, Math.max(measureLengths.get(i), measures.get(i).length));
                if (measures.get(i).notatedLength != null) notatedLengths.putIfAbsent(i, measures.get(i).notatedLength);
            }
        }
        // OMR can misread a duration in one measure. Keep that error local instead of
        // shifting every later note, while preserving actual lengths for implicit/pickup bars.
        for (Map.Entry<Integer, Long> entry : notatedLengths.entrySet()) {
            if (!measureLengths.get(entry.getKey()).equals(entry.getValue())) {
                logger.warn("Measure {} spans {} MIDI ticks; using its notated {}-tick boundary",
                        entry.getKey() + 1, measureLengths.get(entry.getKey()), entry.getValue());
            }
            measureLengths.set(entry.getKey(), entry.getValue());
        }
        List<Integer> order = playbackOrder(sp, measureLengths.size());

        int partIndex = 0;
        for (ScorePartwise.Part part : sp.getPart()) {
            Track track = sequence.createTrack();

            int[] cp = extractChannelProgram(part, partIndex);
            int channel = cp[0];
            int program = cp[1];

            ShortMessage pc = new ShortMessage();
            pc.setMessage(ShortMessage.PROGRAM_CHANGE, channel, program, 0);
            track.add(new MidiEvent(pc, 0));

            writePart(parts.get(partIndex), order, measureLengths, track, meta, channel, partIndex == 0);
            partIndex++;
        }

        return sequence;
    }

    private record TieKey(int pitch, String voice, BigInteger staff) {}

    private record PlayedNote(TieKey key, long onset, long duration, boolean start, boolean stop) {}

    private record Tempo(long onset, BigDecimal bpm) {}

    private record Signature(long onset, int type, byte[] data) {}

    private static class MeasureData
    {
        final List<PlayedNote> notes = new ArrayList<>();
        final List<Tempo> tempos = new ArrayList<>();
        final List<Signature> signatures = new ArrayList<>();
        Map<Integer, byte[]> startingSignatures;
        Long notatedLength;
        BigDecimal startingTempo;
        long length;
    }

    /** Parse notation once so repeating a measure restores its original divisions and transpose. */
    private static List<MeasureData> readPart (ScorePartwise.Part part, int ppq)
    {
        List<MeasureData> result = new ArrayList<>();
        BigDecimal divisions = BigDecimal.valueOf(DEFAULT_PPQ);
        BigDecimal tempo = BigDecimal.valueOf(120);
        Map<BigInteger, Integer> transpose = new HashMap<>();
        Map<Integer, byte[]> signatures = new HashMap<>();
        Long meterLength = null;
        for (ScorePartwise.Part.Measure measure : part.getMeasure()) {
            MeasureData data = new MeasureData();
            data.startingTempo = tempo;
            data.startingSignatures = new HashMap<>(signatures);
            long cursor = 0, chordOnset = 0;
            for (Object item : measure.getNoteOrBackupOrForward()) {
                if (item instanceof Attributes attributes) {
                    if (attributes.getDivisions() != null) {
                        if (attributes.getDivisions().signum() <= 0) {
                            throw new IllegalArgumentException("MusicXML divisions must be positive");
                        }
                        divisions = attributes.getDivisions();
                    }
                    for (Transpose t : attributes.getTranspose()) {
                        int semitones = t.getChromatic() == null ? 0 : t.getChromatic().intValue();
                        if (t.getOctaveChange() != null) semitones += 12 * t.getOctaveChange().intValue();
                        if (t.getNumber() == null) transpose.clear();
                        transpose.put(t.getNumber(), semitones);
                    }
                    if (!attributes.getTime().isEmpty()) {
                        byte[] meter = timeSignature(attributes.getTime().get(0));
                        meterLength = meter == null ? null : (meter[0] & 255) * 4L * ppq / (1 << meter[1]);
                        if (meter != null) {
                            data.signatures.add(new Signature(cursor, 0x58, meter));
                            signatures.put(0x58, meter);
                        }
                    }
                    if (!attributes.getKey().isEmpty()) {
                        byte[] key = keySignature(attributes.getKey().get(0),
                                transpose.getOrDefault(BigInteger.ONE, transpose.getOrDefault(null, 0)));
                        if (key != null) {
                            data.signatures.add(new Signature(cursor, 0x59, key));
                            signatures.put(0x59, key);
                        }
                    }
                } else if (item instanceof Note note) {
                    long duration = ticks(note.getDuration(), divisions, ppq);
                    long onset = note.getChord() == null ? cursor : chordOnset;
                    if (note.getPitch() != null && note.getRest() == null) {
                        BigInteger staff = note.getStaff() == null ? BigInteger.ONE : note.getStaff();
                        int shift = transpose.getOrDefault(staff, transpose.getOrDefault(null, 0));
                        int pitch = computeMidiPitch(note.getPitch()) + shift;
                        if (pitch < 0 || pitch > 127) throw new IllegalArgumentException("Pitch outside MIDI range: " + pitch);
                        boolean start = false, stop = false;
                        for (Tie tie : note.getTie()) {
                            start |= tie.getType() == StartStop.START;
                            stop |= tie.getType() == StartStop.STOP;
                        }
                        TieKey key = new TieKey(pitch, Objects.requireNonNullElse(note.getVoice(), "1"), staff);
                        data.notes.add(new PlayedNote(key, onset,
                                note.getGrace() == null ? duration : Math.max(1, (long) ppq * GRACE_TICKS / DEFAULT_PPQ), start, stop));
                    }
                    if (note.getGrace() == null) data.length = Math.max(data.length, onset + duration);
                    if (note.getChord() == null) {
                        chordOnset = cursor;
                        if (note.getGrace() == null) cursor += duration;
                    }
                } else if (item instanceof Backup backup) {
                    cursor = Math.max(0, cursor - ticks(backup.getDuration(), divisions, ppq));
                } else if (item instanceof Forward forward) {
                    cursor += ticks(forward.getDuration(), divisions, ppq);
                    data.length = Math.max(data.length, cursor);
                } else if (item instanceof Direction direction) {
                    Sound sound = direction.getSound();
                    long offset = 0;
                    if (direction.getOffset() != null && direction.getOffset().getSound() == YesNo.YES) {
                        offset = ticks(direction.getOffset().getValue(), divisions, ppq);
                    }
                    if (sound != null && sound.getOffset() != null) offset = ticks(sound.getOffset().getValue(), divisions, ppq);
                    if (sound != null && sound.getTempo() != null) data.tempos.add(new Tempo(cursor + offset, sound.getTempo()));
                } else if (item instanceof Sound sound && sound.getTempo() != null) {
                    long offset = sound.getOffset() == null ? 0 : ticks(sound.getOffset().getValue(), divisions, ppq);
                    data.tempos.add(new Tempo(cursor + offset, sound.getTempo()));
                }
            }
            data.tempos.sort((a, b) -> Long.compare(a.onset, b.onset));
            if (measure.getImplicit() != YesNo.YES && measure.getNonControlling() != YesNo.YES) data.notatedLength = meterLength;
            for (Tempo change : data.tempos) if (change.bpm.signum() > 0) tempo = change.bpm;
            result.add(data);
        }
        return result;
    }

    private static long ticks (BigDecimal duration, BigDecimal divisions, int ppq)
    {
        return duration == null ? 0 : duration.multiply(BigDecimal.valueOf(ppq))
                .divide(divisions, 0, RoundingMode.HALF_UP).longValueExact();
    }

    private static void writePart (List<MeasureData> measures, List<Integer> order,
                                   List<Long> lengths, Track track, Track meta, int channel, boolean conductor)
            throws InvalidMidiDataException
    {
        long measureTick = 0;
        int previous = -1;
        BigDecimal currentTempo = BigDecimal.valueOf(120);
        Map<TieKey, Long> pending = new HashMap<>();
        Map<Integer, byte[]> currentSignatures = new HashMap<>();
        for (int index : order) {
            if (index != previous + 1) closeTies(pending, track, channel);
            if (index < measures.size()) {
                MeasureData data = measures.get(index);
                if (index != previous + 1) {
                    for (Map.Entry<Integer, byte[]> entry : data.startingSignatures.entrySet()) {
                        if (!Arrays.equals(currentSignatures.get(entry.getKey()), entry.getValue())
                                && data.signatures.stream().noneMatch(s -> s.onset == 0 && s.type == entry.getKey())) {
                            if (entry.getKey() != 0x58 || conductor) addSignature(entry.getKey() == 0x58 ? meta : track,
                                    measureTick, entry.getKey(), entry.getValue());
                            currentSignatures.put(entry.getKey(), entry.getValue());
                        }
                    }
                }
                for (Signature signature : data.signatures) {
                    if (signature.type != 0x58 || conductor) addSignature(signature.type == 0x58 ? meta : track,
                            measureTick + signature.onset, signature.type, signature.data);
                    currentSignatures.put(signature.type, signature.data);
                }
                if (index != previous + 1 && currentTempo.compareTo(data.startingTempo) != 0
                        && data.tempos.stream().noneMatch(t -> t.onset == 0)) {
                    addTempo(meta, measureTick, data.startingTempo);
                    currentTempo = data.startingTempo;
                }
                for (Tempo tempo : data.tempos) {
                    addTempo(meta, Math.max(0, measureTick + tempo.onset), tempo.bpm);
                    if (tempo.bpm.signum() > 0) currentTempo = tempo.bpm;
                }
                for (PlayedNote note : data.notes) {
                    long onset = measureTick + note.onset, off = onset + note.duration;
                    if (!note.stop || !pending.containsKey(note.key)) {
                        Long oldOff = pending.remove(note.key);
                        if (oldOff != null) addNoteOff(track, channel, note.key.pitch, oldOff);
                        addNoteOn(track, channel, note.key.pitch, onset);
                    }
                    if (note.start) pending.put(note.key, off);
                    else {
                        addNoteOff(track, channel, note.key.pitch, off);
                        pending.remove(note.key);
                    }
                }
            }
            measureTick += lengths.get(index);
            previous = index;
        }
        closeTies(pending, track, channel);
        MetaMessage end = new MetaMessage();
        end.setMessage(0x2f, new byte[0], 0);
        track.add(new MidiEvent(end, measureTick));
    }

    private static void closeTies (Map<TieKey, Long> pending, Track track, int channel)
            throws InvalidMidiDataException
    {
        for (Map.Entry<TieKey, Long> tie : pending.entrySet()) addNoteOff(track, channel, tie.getKey().pitch, tie.getValue());
        pending.clear();
    }

    /** Standard MIDI can represent one denominator and major/minor key signatures. */
    private static byte[] timeSignature (Time time)
    {
        int numerator = 0, denominator = 0, pairs = 0;
        try {
            for (var element : time.getTimeSignature()) {
                if (element.getName().getLocalPart().equals("beats")) {
                    pairs++;
                    for (String group : element.getValue().split("\\+")) numerator += Integer.parseInt(group.trim());
                } else if (element.getName().getLocalPart().equals("beat-type")) denominator = Integer.parseInt(element.getValue());
            }
        } catch (NumberFormatException ex) { return null; }
        if (pairs != 1 || numerator < 1 || numerator > 255 || denominator < 1 || denominator > 128
                || Integer.bitCount(denominator) != 1) return null;
        int clocks = denominator == 8 && numerator % 3 == 0 ? 36 : Math.max(1, 96 / denominator);
        return new byte[] {(byte) numerator, (byte) Integer.numberOfTrailingZeros(denominator), (byte) clocks, 8};
    }

    private static byte[] keySignature (Key key, int transpose)
    {
        if (key.getFifths() == null || key.getFifths().abs().compareTo(BigInteger.valueOf(7)) > 0) return null;
        if (key.getMode() != null && !key.getMode().equals("major") && !key.getMode().equals("minor")) return null;
        int fifths = key.getFifths().intValue();
        if (Math.floorMod(transpose, 12) != 0) {
            int target = Math.floorMod(7 * fifths + transpose, 12);
            int best = 8;
            for (int candidate = -7; candidate <= 7; candidate++)
                if (Math.floorMod(7 * candidate, 12) == target && Math.abs(candidate) < Math.abs(best)) best = candidate;
            fifths = best;
        }
        return new byte[] {(byte) fifths, (byte) ("minor".equals(key.getMode()) ? 1 : 0)};
    }

    private static void addSignature (Track track, long tick, int type, byte[] data)
            throws InvalidMidiDataException
    {
        MetaMessage message = new MetaMessage();
        message.setMessage(type, data, data.length);
        track.add(new MidiEvent(message, tick));
    }

    private static void addTempo (Track meta, long tick, BigDecimal bpm)
            throws InvalidMidiDataException
    {
        if (bpm.signum() <= 0) return;
        int microsecondsPerQuarter = BigDecimal.valueOf(60_000_000)
                .divide(bpm, 0, RoundingMode.HALF_UP).intValueExact();
        if (microsecondsPerQuarter < 1 || microsecondsPerQuarter > 0xffffff) {
            throw new IllegalArgumentException("Tempo outside MIDI range: " + bpm);
        }
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

    private record RepeatRegion(int start, int end, int times) {}

    private static class RepeatPass
    {
        final RepeatRegion region;
        int pass = 1;
        RepeatPass (RepeatRegion region) { this.region = region; }
    }

    /** The score's repeat signs apply to all parts, even when printed in only one. */
    private static List<Integer> playbackOrder (ScorePartwise sp, int count)
    {
        boolean[] forward = new boolean[count];
        Map<Integer, Integer> backward = new HashMap<>();
        Map<Integer, Set<Integer>> endings = new HashMap<>();
        for (ScorePartwise.Part part : sp.getPart()) {
            Set<Integer> activeEnding = Set.of();
            for (int i = 0; i < part.getMeasure().size(); i++) {
                boolean endingStops = false;
                for (Object item : part.getMeasure().get(i).getNoteOrBackupOrForward()) {
                    if (!(item instanceof Barline barline)) continue;
                    Repeat repeat = barline.getRepeat();
                    if (repeat != null) {
                        if (repeat.getDirection() == BackwardForward.FORWARD) forward[i] = true;
                        else if (repeat.getDirection() == BackwardForward.BACKWARD) {
                            int times = repeat.getTimes() == null ? 2 : repeat.getTimes().intValueExact();
                            if (times < 1 || times > 100) throw new IllegalArgumentException("Unsupported repeat count: " + times);
                            backward.put(i, times);
                        }
                    }
                    Ending ending = barline.getEnding();
                    if (ending != null) {
                        if (ending.getType() == StartStopDiscontinue.START) activeEnding = endingNumbers(ending.getNumber());
                        else endingStops = true;
                    }
                }
                if (!activeEnding.isEmpty()) endings.put(i, activeEnding);
                if (endingStops) activeEnding = Set.of();
            }
        }

        Deque<Integer> starts = new ArrayDeque<>();
        Map<Integer, List<RepeatRegion>> regions = new HashMap<>();
        int implicitStart = 0;
        for (int i = 0; i < count; i++) {
            if (forward[i]) starts.push(i);
            if (backward.containsKey(i)) {
                int start = starts.isEmpty() ? implicitStart : starts.pop();
                RepeatRegion region = new RepeatRegion(start, i, backward.get(i));
                regions.computeIfAbsent(start, key -> new ArrayList<>()).add(region);
                implicitStart = i + 1;
            }
        }
        // An outer repeat must be pushed before an inner repeat sharing its start.
        for (List<RepeatRegion> rs : regions.values()) rs.sort((a, b) -> Integer.compare(b.end, a.end));
        Deque<RepeatPass> active = new ArrayDeque<>();
        List<Integer> order = new ArrayList<>();
        int index = 0, lastPass = 1, steps = 0;
        while (index < count) {
            if (++steps > Math.max(100_000L, (long) count * 100)) {
                throw new IllegalArgumentException("Repeat expansion exceeds supported score size");
            }
            for (RepeatRegion region : regions.getOrDefault(index, List.of())) {
                boolean alreadyActive = active.stream().anyMatch(p -> p.region.equals(region));
                if (!alreadyActive) active.push(new RepeatPass(region));
            }
            Set<Integer> allowed = endings.getOrDefault(index, Set.of());
            int pass = active.isEmpty() ? lastPass : active.peek().pass;
            if (allowed.isEmpty() || allowed.contains(pass)) order.add(index);
            boolean jump = false;
            while (!active.isEmpty() && active.peek().region.end == index) {
                RepeatPass state = active.peek();
                if (state.pass < state.region.times) {
                    state.pass++;
                    index = state.region.start;
                    jump = true;
                    break;
                }
                lastPass = active.pop().pass;
            }
            if (!jump) index++;
        }
        return order;
    }

    private static Set<Integer> endingNumbers (String value)
    {
        Set<Integer> numbers = new HashSet<>();
        if (value == null) return numbers;
        for (String token : value.split(",")) {
            try {
                int number = Integer.parseInt(token.trim());
                if (number > 0) numbers.add(number);
            } catch (NumberFormatException ex) {
                logger.warn("Ignoring non-numeric ending number: {}", token);
            }
        }
        return numbers;
    }

    private static int extractResolution (ScorePartwise sp)
    {
        int resolution = DEFAULT_PPQ;
        for (ScorePartwise.Part part : sp.getPart()) {
            for (ScorePartwise.Part.Measure m : part.getMeasure()) {
                for (Object item : m.getNoteOrBackupOrForward()) {
                    if (item instanceof Attributes) {
                        Attributes a = (Attributes) item;
                        if (a.getDivisions() != null && a.getDivisions().signum() > 0) {
                            BigDecimal value = a.getDivisions().stripTrailingZeros();
                            BigInteger numerator = value.unscaledValue().multiply(BigInteger.TEN.pow(Math.max(0, -value.scale())));
                            BigInteger denominator = BigInteger.TEN.pow(Math.max(0, value.scale()));
                            numerator = numerator.divide(numerator.gcd(denominator));
                            BigInteger current = BigInteger.valueOf(resolution);
                            BigInteger lcm = current.divide(current.gcd(numerator)).multiply(numerator);
                            // Standard MIDI reserves the sign bit for SMPTE timing.
                            if (lcm.compareTo(BigInteger.valueOf(32767)) <= 0) resolution = lcm.intValue();
                        }
                    }
                }
            }
        }
        return resolution;
    }

    /**
     * Extract MIDI channel (0-based) and program (0-based) for the given Part,
     * preferring values from the linked ScorePart's MidiInstrument.
     * Falls back to round-robin channel and Acoustic Grand Piano (program 0).
     */
    private static int[] extractChannelProgram (ScorePartwise.Part part, int fallbackIndex)
    {
        // Channel 10 is percussion in General MIDI, so melodic fallback routing skips it.
        int channel = fallbackIndex % 15;
        if (channel >= 9) channel++;
        int program = 0;

        Object idRef = part.getId();
        if (idRef instanceof ScorePart) {
            ScorePart scorePart = (ScorePart) idRef;
            for (Object o : scorePart.getMidiDeviceAndMidiInstrument()) {
                if (o instanceof MidiInstrument) {
                    MidiInstrument mi = (MidiInstrument) o;
                    if (mi.getMidiChannel() != null) {
                        channel = Math.max(0, Math.min(15, mi.getMidiChannel() - 1));
                    }
                    if (mi.getMidiProgram() != null) {
                        program = Math.max(0, Math.min(127, mi.getMidiProgram() - 1));
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
        byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
        MetaMessage m = new MetaMessage();
        m.setMessage(0x02, bytes, bytes.length);
        meta.add(new MidiEvent(m, 0));
    }
}
