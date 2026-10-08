#ifndef NOTELITE_EVENTS_H
#define NOTELITE_EVENTS_H
#include "pitch.h"
typedef struct {
    int active, midi, candidate, frames, quiet_frames, unreliable_frames;
    int pending_attack, uncertainty, unstable_frames;
    uint64_t id, uncertainty_id;
    double a4, onset_ms, candidate_ms, candidate_evidence_ms, confidence_sum, cents_sum;
    double timing_confidence, candidate_timing_confidence;
    double last_frequency, last_confidence, last_cents, uncertainty_ms, unstable_ms, peak_level;
    unsigned measurements, updates;
    const char *uncertainty_reason;
} nl_events;
void nl_events_init(nl_events *events, double a4);
void nl_events_push(nl_events *events, const nl_pitch_frame *frame);
void nl_events_finish(nl_events *events, uint64_t samples, double sample_rate);
#endif
