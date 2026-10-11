#include "NoteWiseDSP.h"
#include <stdlib.h>
struct nw_dsp { nl_pitch pitch; nl_events events; nl_note_event queue[128]; size_t used, read; };
static void receive(void *context, const nl_note_event *event) {
    nw_dsp *d = context;
    if (d->used < 128) d->queue[d->used++] = *event;
}
nw_dsp *nw_create(double rate, double a4, double min_hz, double max_hz) {
    return nw_create_profile(rate, a4, min_hz, max_hz, 8192);
}
nw_dsp *nw_create_profile(double rate, double a4, double min_hz, double max_hz, size_t window) {
    if (window != 4096 && window != 8192) return NULL;
    nw_dsp *d = calloc(1, sizeof(*d));
    if (!d) return NULL;
    if (!nl_pitch_init(&d->pitch, window, 512, rate, min_hz, max_hz)) { free(d); return NULL; }
    nl_events_init(&d->events, a4); nl_events_set_callback(&d->events, receive, d);
    return d;
}
void nw_destroy(nw_dsp *d) { if (d) { nl_pitch_free(&d->pitch); free(d); } }
void nw_push(nw_dsp *d, const float *samples, size_t count) {
    nl_pitch_frame frame;
    for (size_t i=0; i<count; ++i) if (nl_pitch_push(&d->pitch, samples[i], &frame)) nl_events_push(&d->events, &frame);
}
int nw_poll(nw_dsp *d, nl_note_event *event) {
    if (d->read == d->used) { d->read=d->used=0; return 0; }
    *event = d->queue[d->read++]; return 1;
}
void nw_finish(nw_dsp *d) { nl_events_finish(&d->events, d->pitch.total_samples, d->pitch.sample_rate); }
