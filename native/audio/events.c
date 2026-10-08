#include "events.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

static double maxd(double a, double b) { return a > b ? a : b; }
static void note(nl_events *e, const char *type, double at, uint64_t sample, const char *reason)
{
    int off = strcmp(type, "note-off") == 0;
    double cents = off && e->measurements ? e->cents_sum / e->measurements : e->last_cents;
    double confidence = off && e->measurements ? e->confidence_sum / e->measurements : e->last_confidence;
    char offset[64] = "null";
    if (off) snprintf(offset, sizeof(offset), "%.6f", maxd(e->onset_ms, at));
    double frequency = off ? e->a4 * pow(2, (e->midi - 69 + cents / 100) / 12) : e->last_frequency;
    printf("{\"type\":\"%s\",\"schemaVersion\":1,\"id\":\"n%llu\",\"midi\":%d,\"cents\":%.6f,\"frequency\":%.8f,\"confidence\":%.6f,\"timingConfidence\":%.3f,\"voiced\":%s,\"onsetMs\":%.6f,\"offsetMs\":%s,\"durationMs\":%.6f,\"timeMs\":%.6f,\"sampleCount\":%llu,\"reason\":\"%s\"}\n",
        type, (unsigned long long)e->id, e->midi, cents, frequency, confidence,
        e->timing_confidence, off ? "false" : "true", e->onset_ms, offset,
        strcmp(type, "note-on") == 0 ? 0 : maxd(0, at - e->onset_ms), at,
        (unsigned long long)sample, reason);
}

static void uncertainty(nl_events *e, double at, uint64_t sample, int close)
{
    char offset[64] = "null";
    if (close) snprintf(offset, sizeof(offset), "%.6f", maxd(e->uncertainty_ms, at));
    printf("{\"type\":\"uncertainty\",\"schemaVersion\":1,\"id\":\"u%llu\",\"midi\":null,\"cents\":null,\"frequency\":%.8f,\"confidence\":%.6f,\"voiced\":null,\"onsetMs\":%.6f,\"offsetMs\":%s,\"durationMs\":%.6f,\"timeMs\":%.6f,\"sampleCount\":%llu,\"reason\":\"%s\"}\n",
        (unsigned long long)e->uncertainty_id, e->last_frequency, e->last_confidence,
        e->uncertainty_ms, offset, close ? maxd(0, at - e->uncertainty_ms) : 0,
        at, (unsigned long long)sample, e->uncertainty_reason);
    e->uncertainty = !close;
}

void nl_events_init(nl_events *e, double a4)
{
    memset(e, 0, sizeof(*e)); e->a4 = a4; e->candidate = -1;
}

void nl_events_push(nl_events *e, const nl_pitch_frame *f)
{
    int midi, valid;
    double raw, cents, at = f->end_time_ms;
    const char *unreliable_reason = NULL;
    uint64_t sample = f->end_sample_count;
    e->last_frequency = f->frequency; e->last_confidence = f->clarity;
    if (f->input_rms < .0005) {
        e->candidate = -1; e->frames = 0; e->pending_attack = 0;
        if (++e->quiet_frames >= 3) {
            double release = isfinite(f->quiet_time_ms) ? f->quiet_time_ms : at - 30;
            if (e->active) { note(e, "note-off", release, (uint64_t)llround(maxd(0, release) * 48), "silence"); e->active = 0; }
            if (e->uncertainty) uncertainty(e, release, (uint64_t)llround(maxd(0, release) * 48), 1);
            e->unreliable_frames = e->unstable_frames = 0;
        }
        return;
    }
    e->quiet_frames = 0;
    if (f->onset) { e->pending_attack = 1; e->candidate = -1; e->frames = 0; }
    valid = f->frequency > 0 && f->clarity >= .9 && f->level_rms >= .001;
    raw = valid ? 69 + 12 * log2(f->frequency / e->a4) : 0;
    /* A fading fundamental often leaves a very periodic overtone. A large
     * unarticulated jump needs strong independent evidence; a quiet octave in
     * an existing decay stays uncertain rather than inventing another note.
     * This uses only measured audio and the preceding acoustic identity. */
    if (valid && e->active && !e->pending_attack) {
        double distance = fabs(raw - e->midi);
        if (distance >= 10 && f->clarity < .985) { valid = 0; unreliable_reason = "pitch-ambiguity"; }
        else if (fabs(distance - 12) < .7 && f->level_rms < .12 * e->peak_level) { valid = 0; unreliable_reason = "octave-ambiguity"; }
    }
    if (!valid) {
        e->candidate = -1; e->frames = 0;
        if (++e->unreliable_frames == 1) e->unstable_ms = f->time_ms;
        if (e->unreliable_frames >= 5 && !e->uncertainty) {
            ++e->uncertainty_id; e->uncertainty_ms = e->unstable_ms;
            e->uncertainty_reason = unreliable_reason ? unreliable_reason : f->level_rms < .008 ? "weak-signal" : "aperiodic";
            uncertainty(e, at, sample, 0);
        }
        return;
    }
    e->unreliable_frames = 0;
    midi = (int)floor(raw + .5);
    if (e->active && fabs(raw - e->midi) < .6 && !e->pending_attack) midi = e->midi;
    if (midi < 0 || midi > 127) return;
    cents = (raw - midi) * 100;
    if (e->candidate != midi) {
        e->candidate = midi; e->frames = 1;
        e->candidate_ms = isfinite(f->onset_time_ms) ? f->onset_time_ms : f->pitch_time_ms;
        e->candidate_timing_confidence = isfinite(f->onset_time_ms) ? 1 : .6;
        if (!e->active && isfinite(f->signal_onset_ms) && f->signal_onset_ms >= f->time_ms) {
            e->candidate_ms = f->signal_onset_ms; e->candidate_timing_confidence = 1;
        }
        if (e->uncertainty) { e->candidate_ms = f->pitch_time_ms; e->candidate_timing_confidence = .5; }
        e->candidate_evidence_ms = f->pitch_time_ms;
        if (++e->unstable_frames == 1) e->unstable_ms = e->candidate_ms;
        if (e->unstable_frames >= 5 && !e->uncertainty) {
            ++e->uncertainty_id; e->uncertainty_ms = e->unstable_ms; e->uncertainty_reason = "unstable";
            uncertainty(e, at, sample, 0);
        }
        return;
    }
    if (++e->frames < 3) return;
    e->unstable_frames = 0;
    if (e->uncertainty) uncertainty(e, e->candidate_evidence_ms, (uint64_t)llround(maxd(0, e->candidate_evidence_ms) * 48), 1);
    if (!e->active || e->midi != midi || e->pending_attack) {
        const char *reason = e->pending_attack ? "attack" : "pitch-change";
        if (e->active) note(e, "note-off", e->candidate_ms, (uint64_t)llround(maxd(0, e->candidate_ms) * 48), e->pending_attack ? "rearticulation" : "pitch-change");
        e->active = 1; e->midi = midi; e->onset_ms = e->candidate_ms; ++e->id;
        e->timing_confidence = e->candidate_timing_confidence;
        e->measurements = e->updates = 0; e->cents_sum = e->confidence_sum = 0;
        e->peak_level = f->level_rms;
        e->last_cents = cents; note(e, "note-on", e->onset_ms, (uint64_t)llround(maxd(0, e->onset_ms) * 48), reason);
        e->pending_attack = 0;
    }
    e->last_cents = cents; e->cents_sum += cents; e->confidence_sum += f->clarity; ++e->measurements;
    e->peak_level = maxd(e->peak_level, f->level_rms);
    if (++e->updates % 10 == 0) note(e, "note-update", at, sample, "sustain");
}

void nl_events_finish(nl_events *e, uint64_t samples, double rate)
{
    double at = 1000 * samples / rate;
    if (e->active) { note(e, "note-off", at, samples, "stop"); e->active = 0; }
    if (e->uncertainty) uncertainty(e, at, samples, 1);
    fflush(stdout);
}
