#ifndef NOTELITE_EVENTS_H
#define NOTELITE_EVENTS_H
#include "pitch.h"
typedef struct {
    const char *type, *reason;
    uint64_t id, sample_count;
    int midi, voiced;
    double cents, frequency, confidence, timing_confidence;
    double onset_ms, offset_ms, duration_ms, time_ms;
} nl_note_event;
typedef void (*nl_event_callback)(void *context, const nl_note_event *event);
typedef struct {
    int active, midi, candidate, frames, quiet_frames, unreliable_frames;
    int pending_attack, uncertainty, unstable_frames;
    uint64_t id, uncertainty_id;
    double a4, onset_ms, candidate_ms, candidate_evidence_ms, confidence_sum, cents_sum;
    double timing_confidence, candidate_timing_confidence;
    double last_frequency, last_confidence, last_cents, uncertainty_ms, unstable_ms, peak_level;
    unsigned measurements, updates;
    const char *uncertainty_reason;
    nl_event_callback callback;
    void *callback_context;
} nl_events;
void nl_events_init(nl_events *events, double a4);
/* Optional native delivery; unset preserves the command-line JSON protocol. */
void nl_events_set_callback(nl_events *events, nl_event_callback callback, void *context);
void nl_events_push(nl_events *events, const nl_pitch_frame *frame);
void nl_events_finish(nl_events *events, uint64_t samples, double sample_rate);
#endif
