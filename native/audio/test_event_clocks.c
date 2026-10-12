/* Production C wrapper regression; no microphone, model or score is required.
 * gcc -O2 test_event_clocks.c pitch.c events.c ../../apple/NoteLite/NoteWiseDSP.c -lm -o test-event-clocks
 */
#include "../../apple/NoteLite/NoteWiseDSP.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void check_clock(const nl_note_event *event, double rate) {
    assert(isfinite(event->time_ms));
    assert(fabs((double)event->sample_count - event->time_ms * rate / 1000) <= .51);
}

static int on_count, off_count, uncertainty_count;
static double frame_rate;
static void receive(void *context, const nl_note_event *event) {
    (void)context;
    check_clock(event, frame_rate);
    if (strcmp(event->type, "note-on") == 0) ++on_count;
    if (strcmp(event->type, "note-off") == 0) ++off_count;
    if (strcmp(event->type, "uncertainty") == 0) ++uncertainty_count;
}

static void frame_clock(double rate) {
    nl_events state;
    nl_pitch_frame frame;
    frame_rate = rate;
    on_count = off_count = uncertainty_count = 0;
    nl_events_init(&state, 440);
    nl_events_set_callback(&state, receive, NULL);
    memset(&frame, 0, sizeof(frame));
    frame.frequency = 440; frame.clarity = .99; frame.input_rms = .1; frame.level_rms = .1;
    frame.signal_onset_ms = frame.quiet_time_ms = NAN;
    frame.onset_time_ms = frame.pitch_time_ms = 100;
    for (int index = 0; index < 3; ++index) {
        frame.end_time_ms = 200 + index * 10;
        frame.end_sample_count = (uint64_t)llround(frame.end_time_ms * rate / 1000);
        nl_events_push(&state, &frame);
    }
    frame.clarity = .2; frame.onset_time_ms = NAN;
    frame.time_ms = frame.pitch_time_ms = 270;
    for (int index = 0; index < 5; ++index) {
        frame.end_time_ms = 300 + index * 10;
        frame.end_sample_count = (uint64_t)llround(frame.end_time_ms * rate / 1000);
        nl_events_push(&state, &frame);
    }
    frame.clarity = .99; frame.onset_time_ms = frame.pitch_time_ms = 350;
    for (int index = 0; index < 3; ++index) {
        frame.end_time_ms = 370 + index * 10;
        frame.end_sample_count = (uint64_t)llround(frame.end_time_ms * rate / 1000);
        nl_events_push(&state, &frame);
    }
    frame.input_rms = 0; frame.quiet_time_ms = 450;
    for (int index = 0; index < 3; ++index) {
        frame.end_time_ms = 460 + index * 10;
        frame.end_sample_count = (uint64_t)llround(frame.end_time_ms * rate / 1000);
        nl_events_push(&state, &frame);
    }
    nl_events_finish(&state, (uint64_t)llround(rate / 2), rate);
    assert(on_count == 1 && off_count == 1 && uncertainty_count == 2);
}

static void actual_pcm_clock(double rate) {
    nw_dsp *dsp = nw_create(rate, 440, 27.5, 5000);
    assert(dsp != NULL);
    int ons = 0, offs = 0, checked = 0;
    const size_t total = (size_t)(rate * .8);
    for (size_t start = 0; start < total; start += 4096) {
        float samples[4096];
        const size_t length = total - start > 4096 ? 4096 : total - start;
        for (size_t index = 0; index < length; ++index) {
            double elapsed = (double)(start + index) / rate - .1;
            samples[index] = elapsed >= 0 && elapsed < .4 ? (float)(.2 * sin(2 * 3.141592653589793 * 440 * elapsed)) : 0;
        }
        nw_push(dsp, samples, length);
        nl_note_event event;
        while (nw_poll(dsp, &event)) {
            check_clock(&event, rate); ++checked;
            if (strcmp(event.type, "note-on") == 0) { ++ons; assert(event.midi == 69); }
            if (strcmp(event.type, "note-off") == 0) { ++offs; assert(strcmp(event.reason, "silence") == 0); }
        }
    }
    nw_finish(dsp);
    nl_note_event event;
    while (nw_poll(dsp, &event)) { check_clock(&event, rate); ++checked; }
    nw_destroy(dsp);
    assert(ons == 1 && offs == 1 && checked > 2);
    printf("{\"sampleRate\":%.0f,\"actualDSP\":true,\"noteOns\":%d,\"noteOffs\":%d,\"eventsChecked\":%d,\"uncertaintyFrameClockChecked\":true}\n", rate, ons, offs, checked);
}

int main(void) {
    const double rates[] = {44100, 48000, 96000};
    for (size_t index = 0; index < sizeof(rates) / sizeof(rates[0]); ++index) {
        frame_clock(rates[index]);
        actual_pcm_clock(rates[index]);
    }
    return 0;
}
