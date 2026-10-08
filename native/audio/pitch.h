#ifndef NOTELITE_PITCH_H
#define NOTELITE_PITCH_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    double frequency, clarity, rms, time_ms, onset_time_ms, pitch_time_ms;
    uint64_t sample_count;
    int onset;
} nl_pitch_frame;

typedef struct {
    size_t window, hop, fft_size, used, until_hop;
    double sample_rate, min_frequency, max_frequency;
    float *samples;
    double *real, *imag, *energy, *nsdf, *cmnd;
    double envelope, valley, hop_energy, fast_energy, onset_frequency;
    size_t hop_samples;
    uint64_t total_samples, last_onset, pending_onset, associated_onset;
    int voiced, onset_armed;
} nl_pitch;

int nl_pitch_init(nl_pitch *p, size_t window, size_t hop, double sample_rate,
                  double min_frequency, double max_frequency);
void nl_pitch_free(nl_pitch *p);
/* Feed every sample exactly once. Returns 1 only when a full causal window is ready. */
int nl_pitch_push(nl_pitch *p, float sample, nl_pitch_frame *frame);
#endif
