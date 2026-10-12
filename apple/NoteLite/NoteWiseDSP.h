#ifndef NOTEWISE_DSP_H
#define NOTEWISE_DSP_H
#include <stddef.h>
#include "../../native/audio/events.h"
typedef struct nw_dsp nw_dsp;
nw_dsp *nw_create(double rate, double a4, double min_hz, double max_hz);
nw_dsp *nw_create_profile(double rate, double a4, double min_hz, double max_hz, size_t window);
void nw_destroy(nw_dsp *dsp);
void nw_push(nw_dsp *dsp, const float *samples, size_t count);
int nw_poll(nw_dsp *dsp, nl_note_event *event);
void nw_finish(nw_dsp *dsp);
#endif
