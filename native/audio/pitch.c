/* Original NoteLite implementation of the published MPM and YIN equations.
 * MIT license: see the repository LICENSE. No upstream pitch code is copied. */
#include "pitch.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define NL_PI 3.14159265358979323846

static void fft(double *r, double *im, size_t n, int inverse)
{
    size_t i, j, width;
    for (i = 1, j = 0; i < n; ++i) {
        size_t bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            double t = r[i]; r[i] = r[j]; r[j] = t;
            t = im[i]; im[i] = im[j]; im[j] = t;
        }
    }
    for (width = 2; width <= n; width <<= 1) {
        double angle = (inverse ? 2 : -2) * NL_PI / (double)width;
        double wr = cos(angle), wi = sin(angle);
        for (i = 0; i < n; i += width) {
            double ur = 1, ui = 0;
            for (j = 0; j < width / 2; ++j) {
                size_t a = i + j, b = a + width / 2;
                double br = r[b] * ur - im[b] * ui;
                double bi = r[b] * ui + im[b] * ur;
                double next = ur * wr - ui * wi;
                r[b] = r[a] - br; im[b] = im[a] - bi;
                r[a] += br; im[a] += bi;
                ui = ur * wi + ui * wr; ur = next;
            }
        }
    }
    if (inverse) for (i = 0; i < n; ++i) { r[i] /= n; im[i] /= n; }
}

static double clamp(double v, double lo, double hi)
{ return v < lo ? lo : v > hi ? hi : v; }

static double interpolated_lag(const double *v, size_t i)
{
    double divisor = v[i - 1] - 2 * v[i] + v[i + 1];
    return (double)i + (fabs(divisor) < 1e-12 ? 0 :
        clamp(0.5 * (v[i - 1] - v[i + 1]) / divisor, -0.5, 0.5));
}

int nl_pitch_init(nl_pitch *p, size_t window, size_t hop, double rate,
                  double minimum, double maximum)
{
    memset(p, 0, sizeof(*p));
    if (window < 1024 || window > 16384 || (window & (window - 1)) ||
        hop == 0 || hop > window || rate <= 0 || minimum < 20 ||
        maximum <= minimum || maximum > 10000 || maximum >= rate / 2 ||
        rate / minimum > window * 0.75) return 0;
    p->window = window; p->hop = hop; p->fft_size = 2 * window;
    p->sample_rate = rate; p->min_frequency = minimum; p->max_frequency = maximum;
    p->samples = (float *)calloc(window, sizeof(float));
    p->real = (double *)calloc(2 * window, sizeof(double));
    p->imag = (double *)calloc(2 * window, sizeof(double));
    p->energy = (double *)calloc(window + 1, sizeof(double));
    p->nsdf = (double *)calloc(window, sizeof(double));
    p->cmnd = (double *)calloc(window, sizeof(double));
    p->last_onset = p->pending_onset = p->associated_onset = UINT64_MAX;
    p->quiet_start = UINT64_MAX;
    p->signal_start = UINT64_MAX;
    p->onset_armed = 1;
    if (!p->samples || !p->real || !p->imag || !p->energy || !p->nsdf || !p->cmnd) {
        nl_pitch_free(p); return 0;
    }
    return 1;
}

void nl_pitch_free(nl_pitch *p)
{
    free(p->samples); free(p->real); free(p->imag);
    free(p->energy); free(p->nsdf); free(p->cmnd);
    memset(p, 0, sizeof(*p));
}

static void update_envelope(nl_pitch *p, double hop_rms, uint64_t hop_start)
{
    double previous_fast = sqrt(p->fast_energy);
    p->input_rms = hop_rms;
    if (hop_rms < .0005) {
        if (p->quiet_start == UINT64_MAX) p->quiet_start = hop_start;
        p->signal_start = UINT64_MAX;
    } else {
        p->quiet_start = UINT64_MAX;
        if (p->signal_start == UINT64_MAX) p->signal_start = hop_start;
    }
    if (p->fast_energy == 0) p->fast_energy = hop_rms * hop_rms;
    p->fast_energy = 0.75 * p->fast_energy + 0.25 * hop_rms * hop_rms;
    double level = sqrt(p->fast_energy);
    if (p->envelope == 0) p->envelope = level;
    p->envelope = 0.9 * p->envelope + 0.1 * level;
    if (level < p->envelope * 0.68) p->onset_armed = 1;
    if (p->onset_armed) p->valley = p->valley == 0 ? level : fmin(p->valley, level);
    if (level < 0.003 && hop_rms < 0.003) {
        p->voiced = 0; p->onset_armed = 1; p->valley = level;
        p->pending_onset = p->associated_onset = UINT64_MAX; p->onset_frequency = 0;
    }
    /* Record the first short-hop attack before waiting for a full pitch window.
     * This timestamp is independent of FFT window length and delivery latency. */
    if (p->onset_armed && p->pending_onset == UINT64_MAX &&
        hop_rms >= 0.005 && (!p->voiced ||
        (hop_rms > fmax(0.005, p->valley * 2) && hop_rms > previous_fast * 1.35)) &&
        (p->last_onset == UINT64_MAX || hop_start - p->last_onset >= (uint64_t)(p->sample_rate * 0.08)))
        p->pending_onset = hop_start;
}

static void analyze(nl_pitch *p, nl_pitch_frame *frame)
{
    size_t i, n = p->window, maximum = (size_t)ceil(p->sample_rate / p->min_frequency);
    size_t minimum = (size_t)floor(p->sample_rate / p->max_frequency);
    size_t peak = 0, yin = 0, peak_start;
    double mean = 0, sum = 0, max_peak = 0, running = 0;
    double mpm_frequency = 0, yin_frequency = 0;
    if (minimum < 2) minimum = 2;
    if (maximum > n - 2) maximum = n - 2;
    memset(frame, 0, sizeof(*frame));
    frame->sample_count = p->total_samples - n;
    frame->time_ms = 1000 * (double)frame->sample_count / p->sample_rate;
    frame->pitch_time_ms = 1000 * ((double)frame->sample_count + (double)n / 2) / p->sample_rate;
    frame->onset_time_ms = NAN;
    frame->input_rms = p->input_rms; frame->level_rms = sqrt(p->fast_energy);
    frame->quiet_time_ms = p->quiet_start == UINT64_MAX ? NAN : 1000 * (double)p->quiet_start / p->sample_rate;
    frame->signal_onset_ms = p->signal_start == UINT64_MAX ? NAN : 1000 * (double)p->signal_start / p->sample_rate;
    frame->end_sample_count = p->total_samples;
    frame->end_time_ms = 1000 * (double)p->total_samples / p->sample_rate;
    for (i = 0; i < n; ++i) {
        mean += p->samples[i]; sum += (double)p->samples[i] * p->samples[i];
    }
    frame->rms = sqrt(sum / n); mean /= n;
    if (frame->rms >= 0.001) {
        p->energy[0] = 0;
        for (i = 0; i < n; ++i) {
            p->real[i] = (double)p->samples[i] - mean;
            p->energy[i + 1] = p->energy[i] + p->real[i] * p->real[i];
        }
        memset(p->real + n, 0, n * sizeof(double));
        memset(p->imag, 0, p->fft_size * sizeof(double));
        fft(p->real, p->imag, p->fft_size, 0);
        for (i = 0; i < p->fft_size; ++i) {
            p->real[i] = p->real[i] * p->real[i] + p->imag[i] * p->imag[i];
            p->imag[i] = 0;
        }
        fft(p->real, p->imag, p->fft_size, 1);
        p->nsdf[0] = 1; p->cmnd[0] = 1;
        for (i = 1; i <= maximum + 1; ++i) {
            double e = p->energy[n - i] + p->energy[n] - p->energy[i];
            double d = fmax(0, e - 2 * p->real[i]) / (double)(n - i);
            p->nsdf[i] = e > 1e-20 ? clamp(2 * p->real[i] / e, -1, 1) : 0;
            running += d;
            p->cmnd[i] = running > 1e-20 ? d * (double)i / running : 1;
        }
        /* MPM: skip the zero-lag positive lobe, then compare genuine local maxima. */
        i = 1;
        while (i < maximum && p->nsdf[i] > 0) ++i;
        peak_start = i > minimum ? i : minimum;
        for (; i <= maximum; ++i) if (i >= minimum &&
            p->nsdf[i] > p->nsdf[i - 1] && p->nsdf[i] >= p->nsdf[i + 1])
            max_peak = fmax(max_peak, p->nsdf[i]);
        for (i = peak_start; i <= maximum; ++i) if (
            p->nsdf[i] > p->nsdf[i - 1] && p->nsdf[i] >= p->nsdf[i + 1] &&
            p->nsdf[i] >= fmax(0.75, 0.93 * max_peak)) { peak = i; break; }
        /* YIN cumulative mean normalized difference with overlap-length normalization.
         * Find the first local minimum under 0.15, avoiding a lower-octave global minimum. */
        for (i = minimum; i <= maximum; ++i) if (p->cmnd[i] < 0.15 &&
            p->cmnd[i] < p->cmnd[i - 1] && p->cmnd[i] <= p->cmnd[i + 1]) {
            yin = i; break;
        }
        if (peak) mpm_frequency = p->sample_rate / interpolated_lag(p->nsdf, peak);
        if (yin) yin_frequency = p->sample_rate / interpolated_lag(p->cmnd, yin);
        if (mpm_frequency > 0 && yin_frequency > 0 &&
            fabs(1200 * log2(mpm_frequency / yin_frequency)) <= 60) {
            frame->frequency = mpm_frequency;
            frame->clarity = fmin(p->nsdf[peak], 1 - p->cmnd[yin]);
            if (frame->frequency < p->min_frequency || frame->frequency > p->max_frequency)
                frame->frequency = frame->clarity = 0;
        }
    }
    if (frame->frequency > 0 && frame->clarity >= 0.8 && sqrt(p->fast_energy) >= 0.005) {
        if (p->pending_onset != UINT64_MAX) {
            frame->onset = 1; p->last_onset = p->pending_onset;
            p->associated_onset = p->pending_onset; p->pending_onset = UINT64_MAX;
            p->onset_frequency = frame->frequency;
            p->onset_armed = 0; p->valley = 0;
            /* Start a fresh envelope reference for this attack. A preceding
             * louder note can leave the slow envelope high through a short
             * rest; comparing a new, still-rising soft attack to that old
             * level spuriously re-arms it without any actual amplitude fall. */
            p->envelope = sqrt(p->fast_energy);
        }
        p->voiced = 1;
        if (p->associated_onset != UINT64_MAX && p->onset_frequency > 0) {
            if (fabs(1200 * log2(frame->frequency / p->onset_frequency)) > 70) {
                /* A continuous legato pitch change must not inherit the prior
                 * note's attack, even while that attack remains in the window. */
                p->associated_onset = UINT64_MAX;
            }
            if (p->associated_onset != UINT64_MAX)
                frame->onset_time_ms = 1000 * (double)p->associated_onset / p->sample_rate;
        }
    }
}

int nl_pitch_push(nl_pitch *p, float sample, nl_pitch_frame *frame)
{
    if (!isfinite(sample)) sample = 0;
    p->samples[p->used++] = sample;
    p->total_samples++;
    p->hop_energy += (double)sample * sample; p->hop_samples++;
    if (p->hop_samples == p->hop) {
        update_envelope(p, sqrt(p->hop_energy / p->hop_samples), p->total_samples - p->hop_samples);
        p->hop_energy = 0; p->hop_samples = 0;
    }
    if (p->used < p->window) return 0;
    analyze(p, frame);
    memmove(p->samples, p->samples + p->hop, (p->window - p->hop) * sizeof(float));
    p->used = p->window - p->hop;
    return 1;
}
