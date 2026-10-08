/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Sounding-pitch traversal with separate source identities and repeat occurrences. */
public record PracticeTimeline(List<Group> groups, double bpm) {
    public record Note(String sourceNoteId, String occurrenceId, String part, String staff,
                       int midi, double onsetMs, double durationMs) {
        public Map<String,Object> snapshot() {
            Map<String,Object> out = new LinkedHashMap<>();
            out.put("id", sourceNoteId); out.put("sourceNoteId", sourceNoteId); out.put("occurrenceId", occurrenceId);
            out.put("part", part); out.put("staff", staff); out.put("midi", midi);
            out.put("onsetMs", onsetMs); out.put("durationMs", durationMs); return out;
        }
    }
    public record Group(int index, double onsetMs, String measure, int mi, double beat, List<Note> notes) {
        public List<Integer> pitches() { return notes.stream().map(Note::midi).distinct().toList(); }
        public Map<String,Object> snapshot() {
            Map<String,Object> out=location();out.put("onsetMs",onsetMs);out.put("notes",notes.stream().map(Note::snapshot).toList());return out;
        }
        public Map<String,Object> location() {
            Map<String,Object> out = new LinkedHashMap<>();
            out.put("index", index); out.put("measure", measure); out.put("mi", mi); out.put("beat", beat);
            out.put("sourceNoteIds", notes.stream().map(Note::sourceNoteId).toList());
            out.put("occurrenceIds", notes.stream().map(Note::occurrenceId).toList()); return out;
        }
    }
    public PracticeTimeline {
        if (!Double.isFinite(bpm) || bpm < 20 || bpm > 400 || groups == null || groups.isEmpty())
            throw new IllegalArgumentException("请选择有效的练习段落与速度。");
        groups = List.copyOf(groups);
    }
    /** Legacy quarter-beat groups or normalized explicit millisecond groups. */
    public static PracticeTimeline fromGroups(List<?> input, double bpm) {
        if (input == null || input.isEmpty()) throw new IllegalArgumentException("所选范围没有可练习的音符。");
        double beat = 60000 / bpm, first = number(map(input.getFirst()), "onsetMs", Double.NaN);
        if (!Double.isFinite(first)) first = number(map(input.getFirst()), "onset", 0) * beat;
        List<Group> groups = new ArrayList<>(); double previous = -1;
        for (Object value : input) {
            Map<?,?> g = map(value); int index = groups.size();
            double onset = number(g, "onsetMs", number(g, "onset", 0) * beat) - first;
            if (!Double.isFinite(onset) || onset < previous || onset < 0) throw new IllegalArgumentException("乐谱遍历时间无效。");
            previous = onset;
            String measure = string(g, "measure", Integer.toString(index + 1));
            int mi = (int) number(g, "mi", index); double position = number(g, "beat", 1);
            if (!(g.get("notes") instanceof List<?> raw) || raw.isEmpty()) throw new IllegalArgumentException("起音位置缺少音符。");
            List<Note> notes = new ArrayList<>();
            for (Object noteValue : raw) {
                Map<?,?> n = map(noteValue); double pitch = number(n, "midi", Double.NaN);
                double duration = number(n, "durationMs", number(n, "duration", 0) * beat);
                if (pitch != Math.rint(pitch) || pitch < 0 || pitch > 127 || !Double.isFinite(pitch)
                        || !Double.isFinite(duration) || duration <= 0) throw new IllegalArgumentException("乐谱实声音高或时值无效。");
                String source = string(n, "sourceNoteId", string(n, "id", "part:" + index + ":" + notes.size()));
                String occurrence = string(n, "occurrenceId", source + "@" + index);
                notes.add(new Note(source, occurrence, string(n,"part",""), string(n,"staff","1"), (int)pitch, onset, duration));
            }
            groups.add(new Group(index,onset,measure,mi,position,List.copyOf(notes)));
        }
        return new PracticeTimeline(groups,bpm);
    }
    static Map<?,?> map(Object value) { if (value instanceof Map<?,?> m) return m; throw new IllegalArgumentException("练习数据格式无效。"); }
    static double number(Map<?,?> map, String key, double fallback) { Object value=map.get(key); return value instanceof Number n ? n.doubleValue() : fallback; }
    static String string(Map<?,?> map, String key, String fallback) { Object value=map.get(key); return value instanceof String s && !s.isBlank() ? s : fallback; }
}
