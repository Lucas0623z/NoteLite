/* Windows-local capture, recording and offline analysis. See README.md for protocol. */
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <math.h>
#include "pitch.h"
#include "events.h"

#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#define MA_NO_ENGINE
#define MA_NO_GENERATION
#define MA_NO_MP3
#define MA_NO_FLAC
#define MINIAUDIO_IMPLEMENTATION
#include "vendor/miniaudio/miniaudio.h"

#define SAMPLE_RATE 48000
#define HOP 480
#define QUEUE_CAPACITY 262144u

typedef struct {
    nl_pitch pitch;
    nl_events events;
    ma_encoder recorder;
    float *queue;
    volatile LONG64 read_index, write_index;
    volatile LONG stopping, capture_stopped, ready, fatal;
    HANDLE available, stop_event;
    int recording;
    uint64_t consumed;
} capture_state;

static void error_line(const char *code, const char *message)
{
    /* Messages are fixed developer strings, never unescaped file paths. */
    printf("{\"type\":\"error\",\"code\":\"%s\",\"message\":\"%s\"}\n", code, message);
    fflush(stdout);
}

static void frame_line(const nl_pitch_frame *f)
{
    char onset_time[64] = "null";
    if (isfinite(f->onset_time_ms)) snprintf(onset_time, sizeof(onset_time), "%.6f", f->onset_time_ms);
    const char *voiced = f->input_rms < .0005 ? "false" : f->frequency > 0 && f->clarity >= .9 ? "true" : "null";
    printf("{\"frequency\":%.8f,\"clarity\":%.6f,\"rms\":%.8f,\"timeMs\":%.6f,\"onset\":%s,\"sampleCount\":%llu,\"onsetTimeMs\":%s,\"pitchTimeMs\":%.6f,\"voiced\":%s,\"confidence\":%.6f,\"inputRms\":%.8f,\"endTimeMs\":%.6f}\n",
        f->frequency, f->clarity, f->rms, f->time_ms,
        f->onset ? "true" : "false", (unsigned long long)f->sample_count,
        onset_time, f->pitch_time_ms, voiced, f->clarity, f->input_rms, f->end_time_ms);
}

static void stopped_line(uint64_t samples)
{
    printf("{\"type\":\"stopped\",\"sampleCount\":%llu,\"timeMs\":%.6f}\n",
        (unsigned long long)samples, 1000.0 * (double)samples / SAMPLE_RATE);
    fflush(stdout);
}

static void capture_callback(ma_device *device, void *output, const void *input, ma_uint32 count)
{
    capture_state *s = (capture_state *)device->pUserData;
    uint64_t write, read;
    size_t first;
    (void)output;
    if (InterlockedCompareExchange(&s->stopping, 0, 0)) return;
    write = (uint64_t)InterlockedCompareExchange64(&s->write_index, 0, 0);
    read = (uint64_t)InterlockedCompareExchange64(&s->read_index, 0, 0);
    if (!input || count > QUEUE_CAPACITY || write - read > QUEUE_CAPACITY - count) {
        InterlockedExchange(&s->fatal, input ? 1 : 2);
        InterlockedExchange(&s->stopping, 1);
        SetEvent(s->stop_event); SetEvent(s->available); return;
    }
    first = QUEUE_CAPACITY - (size_t)(write % QUEUE_CAPACITY);
    if (first > count) first = count;
    memcpy(s->queue + write % QUEUE_CAPACITY, input, first * sizeof(float));
    if (count > first) memcpy(s->queue, (const float *)input + first, (count - first) * sizeof(float));
    InterlockedExchange64(&s->write_index, (LONG64)(write + count));
    SetEvent(s->available);
}

static void notification_callback(const ma_device_notification *notification)
{
    capture_state *s = (capture_state *)notification->pDevice->pUserData;
    if (notification->type == ma_device_notification_type_stopped &&
        !InterlockedCompareExchange(&s->stopping, 0, 0)) {
        InterlockedExchange(&s->fatal, 3);
        InterlockedExchange(&s->stopping, 1);
        SetEvent(s->stop_event); SetEvent(s->available);
    }
}

static int process_samples(capture_state *s, const float *samples, size_t count)
{
    size_t i;
    if (s->recording) {
        ma_uint64 written = 0;
        ma_int16 recorded[4096];
        if (count > 4096 || s->consumed + count > (UINT32_MAX - 128u) / sizeof(ma_int16)) {
            error_line("RECORD_TOO_LARGE", "The recording exceeds the WAV container size limit.");
            InterlockedExchange(&s->fatal, 4); return 0;
        }
        ma_pcm_f32_to_s16(recorded, samples, count, ma_dither_mode_none);
        if (ma_encoder_write_pcm_frames(&s->recorder, recorded, count, &written) != MA_SUCCESS || written != count) {
            error_line("RECORD_WRITE_FAILED", "Could not write the complete local WAV recording.");
            InterlockedExchange(&s->fatal, 4); return 0;
        }
    }
    for (i = 0; i < count; ++i) {
        nl_pitch_frame frame;
        if (nl_pitch_push(&s->pitch, samples[i], &frame)) { frame_line(&frame); nl_events_push(&s->events, &frame); }
    }
    s->consumed += count;
    fflush(stdout); return 1;
}

static DWORD WINAPI analysis_worker(void *context)
{
    capture_state *s = (capture_state *)context;
    float block[4096];
    for (;;) {
        uint64_t write, read;
        size_t count, first;
        if (!InterlockedCompareExchange(&s->ready, 0, 0)) {
            if (InterlockedCompareExchange(&s->capture_stopped, 0, 0)) break;
            WaitForSingleObject(s->available, 20); continue;
        }
        write = (uint64_t)InterlockedCompareExchange64(&s->write_index, 0, 0);
        read = (uint64_t)InterlockedCompareExchange64(&s->read_index, 0, 0);
        if (write == read) {
            if (InterlockedCompareExchange(&s->capture_stopped, 0, 0)) break;
            WaitForSingleObject(s->available, 20); continue;
        }
        count = (size_t)(write - read);
        if (count > 4096) count = 4096;
        first = QUEUE_CAPACITY - (size_t)(read % QUEUE_CAPACITY);
        if (first > count) first = count;
        memcpy(block, s->queue + read % QUEUE_CAPACITY, first * sizeof(float));
        if (count > first) memcpy(block + first, s->queue, (count - first) * sizeof(float));
        InterlockedExchange64(&s->read_index, (LONG64)(read + count));
        if (!process_samples(s, block, count)) {
            InterlockedExchange(&s->stopping, 1); SetEvent(s->stop_event); break;
        }
    }
    return 0;
}

static DWORD WINAPI stdin_worker(void *context)
{
    capture_state *s = (capture_state *)context;
    HANDLE handle = GetStdHandle(STD_INPUT_HANDLE);
    char input[128], line[32];
    DWORD length, i; size_t used = 0;
    while (ReadFile(handle, input, sizeof(input), &length, NULL) && length) {
        for (i = 0; i < length; ++i) {
            if (input[i] == '\n') {
                line[used] = 0; used = 0;
                if (strcmp(line, "STOP") == 0) { SetEvent(s->stop_event); return 0; }
            } else if (input[i] != '\r' && used < sizeof(line) - 1) line[used++] = input[i];
        }
    }
    SetEvent(s->stop_event); return 0;
}

static int offline(capture_state *s, const wchar_t *path)
{
    ma_decoder decoder;
    ma_decoder_config config = ma_decoder_config_init(ma_format_f32, 1, SAMPLE_RATE);
    float block[4096];
    ma_uint64 read;
    ma_result result;
    if (ma_decoder_init_file_w(path, &config, &decoder) != MA_SUCCESS) {
        error_line("ANALYZE_OPEN_FAILED", "Could not decode the local WAV file."); return 2;
    }
    printf("{\"type\":\"ready\",\"sampleRate\":48000,\"timeMs\":0,\"mode\":\"analyze\"}\n");
    fflush(stdout);
    s->ready = 1;
    do {
        read = 0;
        result = ma_decoder_read_pcm_frames(&decoder, block, 4096, &read);
        if (read && !process_samples(s, block, (size_t)read)) { ma_decoder_uninit(&decoder); return 3; }
        if (result != MA_SUCCESS && result != MA_AT_END) {
            error_line("ANALYZE_DECODE_FAILED", "The WAV file ended with a decode error.");
            ma_decoder_uninit(&decoder); return 2;
        }
    } while (read > 0 && result != MA_AT_END);
    ma_decoder_uninit(&decoder);
    return 0;
}

static int live(capture_state *s, int capture_index, int playback_index, int loopback)
{
    ma_device device;
    ma_context context;
    ma_device_info *inputs, *outputs;
    ma_uint32 input_count, output_count;
    ma_backend wasapi = ma_backend_wasapi;
    ma_device_config config = ma_device_config_init(loopback ? ma_device_type_loopback : ma_device_type_capture);
    HANDLE worker = NULL, control = NULL;
    int result = 0;
    if (ma_context_init(loopback ? &wasapi : NULL, loopback ? 1 : 0, NULL, &context) != MA_SUCCESS) {
        error_line("DEVICE_CONTEXT_FAILED", "Could not initialize Windows audio devices."); return 2;
    }
    if (ma_context_get_devices(&context, &outputs, &output_count, &inputs, &input_count) != MA_SUCCESS ||
        capture_index >= (int)input_count || playback_index >= (int)output_count) {
        error_line("DEVICE_SELECTION_FAILED", "The selected Windows audio device is unavailable."); ma_context_uninit(&context); return 2;
    }
    if (loopback && playback_index >= 0) config.capture.pDeviceID = &outputs[playback_index].id;
    else if (!loopback && capture_index >= 0) config.capture.pDeviceID = &inputs[capture_index].id;
    s->queue = (float *)calloc(QUEUE_CAPACITY, sizeof(float));
    s->available = CreateEventW(NULL, FALSE, FALSE, NULL);
    s->stop_event = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!s->queue || !s->available || !s->stop_event) {
        error_line("CAPTURE_INIT_FAILED", "Could not allocate the local capture queue."); result = 2; goto cleanup;
    }
    config.capture.format = ma_format_f32; config.capture.channels = 1;
    config.sampleRate = SAMPLE_RATE; config.periodSizeInFrames = HOP;
    config.dataCallback = capture_callback; config.notificationCallback = notification_callback;
    config.pUserData = s;
    if (ma_device_init(&context, &config, &device) != MA_SUCCESS) {
        error_line("MICROPHONE_UNAVAILABLE", "Could not open the default Windows capture device."); result = 2; goto cleanup;
    }
    worker = CreateThread(NULL, 0, analysis_worker, s, 0, NULL);
    if (!worker || ma_device_start(&device) != MA_SUCCESS) {
        error_line("CAPTURE_START_FAILED", "Could not start Windows microphone capture."); result = 2;
        InterlockedExchange(&s->stopping, 1); ma_device_uninit(&device);
        InterlockedExchange(&s->capture_stopped, 1); SetEvent(s->available); goto join;
    }
    printf("{\"type\":\"ready\",\"sampleRate\":48000,\"timeMs\":0}\n"); fflush(stdout);
    InterlockedExchange(&s->ready, 1); SetEvent(s->available);
    fprintf(stderr, "NoteLite local audio: miniaudio 0.11.25, MPM/YIN, mono 48000 Hz, window %zu.\n", s->pitch.window);
    control = CreateThread(NULL, 0, stdin_worker, s, 0, NULL);
    if (!control) {
        error_line("CONTROL_START_FAILED", "Could not start the STOP control reader."); result = 2;
    } else WaitForSingleObject(s->stop_event, INFINITE);
    InterlockedExchange(&s->stopping, 1);
    ma_device_uninit(&device);
    InterlockedExchange(&s->capture_stopped, 1); SetEvent(s->available);
join:
    if (worker) { WaitForSingleObject(worker, INFINITE); CloseHandle(worker); }
    if (control) { CancelSynchronousIo(control); WaitForSingleObject(control, 2000); CloseHandle(control); }
    switch (InterlockedCompareExchange(&s->fatal, 0, 0)) {
        case 1: error_line("CAPTURE_OVERFLOW", "Capture queue overflow: recording stopped without dropping or retiming samples."); result = 3; break;
        case 2: error_line("CAPTURE_INVALID_INPUT", "Windows capture supplied an invalid input buffer."); result = 3; break;
        case 3: error_line("CAPTURE_DEVICE_STOPPED", "Windows capture stopped unexpectedly."); result = 3; break;
        case 4: result = 3; break;
    }
cleanup:
    if (s->available) CloseHandle(s->available);
    if (s->stop_event) CloseHandle(s->stop_event);
    free(s->queue); ma_context_uninit(&context); return result;
}

static void json_string(const char *value)
{
    const unsigned char *p = (const unsigned char *)value;
    putchar('"');
    for (; *p; ++p) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static int list_devices(void)
{
    ma_context context; ma_device_info *inputs, *outputs;
    ma_uint32 in_count, out_count, i;
    if (ma_context_init(NULL, 0, NULL, &context) != MA_SUCCESS) { error_line("DEVICE_CONTEXT_FAILED", "Could not enumerate Windows audio devices."); return 2; }
    if (ma_context_get_devices(&context, &outputs, &out_count, &inputs, &in_count) != MA_SUCCESS) {
        ma_context_uninit(&context); error_line("DEVICE_LIST_FAILED", "Could not enumerate Windows audio devices."); return 2;
    }
    printf("{\"type\":\"devices\",\"capture\":[");
    for (i = 0; i < in_count; ++i) {
        if (i) putchar(',');
        printf("{\"index\":%u,\"name\":", i); json_string(inputs[i].name);
        printf(",\"default\":%s}", inputs[i].isDefault ? "true" : "false");
    }
    printf("],\"playback\":[");
    for (i = 0; i < out_count; ++i) {
        if (i) putchar(',');
        printf("{\"index\":%u,\"name\":", i); json_string(outputs[i].name);
        printf(",\"default\":%s}", outputs[i].isDefault ? "true" : "false");
    }
    puts("]}"); ma_context_uninit(&context); return 0;
}

typedef struct {
    capture_state base;
    ma_decoder decoder;
    ma_uint64 source_start, source_end, decoded;
    volatile LONG decoder_done;
    double metronome_bpm;
} playback_state;

static void playback_callback(ma_device *device, void *output, const void *input, ma_uint32 requested)
{
    playback_state *s = (playback_state *)device->pUserData;
    capture_state *q = &s->base;
    uint64_t write, read; size_t count, first;
    (void)input;
    memset(output, 0, requested * 2 * sizeof(float));
    if (InterlockedCompareExchange(&q->stopping, 0, 0)) return;
    write = (uint64_t)InterlockedCompareExchange64(&q->write_index, 0, 0);
    read = (uint64_t)InterlockedCompareExchange64(&q->read_index, 0, 0);
    count = (size_t)(write - read); if (count > requested) count = requested;
    first = QUEUE_CAPACITY - (size_t)(read % QUEUE_CAPACITY); if (first > count) first = count;
    memcpy(output, q->queue + 2 * (read % QUEUE_CAPACITY), first * 2 * sizeof(float));
    if (count > first) memcpy((float *)output + first * 2, q->queue, (count - first) * 2 * sizeof(float));
    InterlockedExchange64(&q->read_index, (LONG64)(read + count)); SetEvent(q->available);
    if (count < requested) {
        if (!InterlockedCompareExchange(&s->decoder_done, 0, 0)) InterlockedExchange(&q->fatal, 1);
        InterlockedExchange(&q->stopping, 1); SetEvent(q->stop_event);
    }
}

static void playback_notification(const ma_device_notification *notification)
{
    playback_state *s = (playback_state *)notification->pDevice->pUserData;
    if (notification->type == ma_device_notification_type_stopped &&
        !InterlockedCompareExchange(&s->base.stopping, 0, 0)) {
        InterlockedExchange(&s->base.fatal, 3); InterlockedExchange(&s->base.stopping, 1);
        SetEvent(s->base.stop_event); SetEvent(s->base.available);
    }
}

static int playback_fill(playback_state *s)
{
    float block[8192];
    ma_uint64 remaining = s->source_end - s->source_start - s->decoded, read = 0;
    ma_result result;
    uint64_t write = (uint64_t)InterlockedCompareExchange64(&s->base.write_index, 0, 0);
    size_t first;
    if (!remaining) { InterlockedExchange(&s->decoder_done, 1); return 0; }
    if (remaining > 4096) remaining = 4096;
    if (s->metronome_bpm > 0) {
        for (ma_uint64 i = 0; i < remaining; ++i) {
            double frame = (double)(s->source_start + s->decoded + i);
            double interval = 60.0 * SAMPLE_RATE / s->metronome_bpm;
            uint64_t beat = (uint64_t)floor(frame / interval);
            double seconds = (frame - (double)beat * interval) / SAMPLE_RATE;
            double hz = beat % 4 == 0 ? 1760 : 1320;
            float click = seconds < .035 ? (float)(.22 * sin(6.2831853071795864769 * hz * seconds) * exp(-120 * seconds)) : 0;
            block[2 * i] = block[2 * i + 1] = click;
        }
        read = remaining; result = MA_SUCCESS;
    } else result = ma_decoder_read_pcm_frames(&s->decoder, block, remaining, &read);
    if ((result != MA_SUCCESS && result != MA_AT_END) || read != remaining) {
        InterlockedExchange(&s->base.fatal, 2); InterlockedExchange(&s->base.stopping, 1);
        SetEvent(s->base.stop_event); return 0;
    }
    first = QUEUE_CAPACITY - (size_t)(write % QUEUE_CAPACITY); if (first > read) first = (size_t)read;
    memcpy(s->base.queue + 2 * (write % QUEUE_CAPACITY), block, first * 2 * sizeof(float));
    if (read > first) memcpy(s->base.queue, block + first * 2, ((size_t)read - first) * 2 * sizeof(float));
    s->decoded += read;
    /* Publish finality before final frames, avoiding a callback race at the end. */
    if (s->decoded == s->source_end - s->source_start) InterlockedExchange(&s->decoder_done, 1);
    InterlockedExchange64(&s->base.write_index, (LONG64)(write + read)); return 1;
}

static DWORD WINAPI playback_worker(void *pointer)
{
    playback_state *s = (playback_state *)pointer;
    uint64_t last_progress = 0;
    while (!InterlockedCompareExchange(&s->base.stopping, 0, 0)) {
        uint64_t read = (uint64_t)InterlockedCompareExchange64(&s->base.read_index, 0, 0);
        uint64_t write = (uint64_t)InterlockedCompareExchange64(&s->base.write_index, 0, 0);
        if (InterlockedCompareExchange(&s->base.ready, 0, 0) && read - last_progress >= 4800) {
            printf("{\"type\":\"playback\",\"sampleCount\":%llu,\"timeMs\":%.6f,\"positionMs\":%.6f}\n",
                (unsigned long long)read, (double)read / 48, (double)(s->source_start + read) / 48);
            fflush(stdout); last_progress = read;
        }
        if (!InterlockedCompareExchange(&s->decoder_done, 0, 0) && write - read <= QUEUE_CAPACITY - 4096) playback_fill(s);
        else WaitForSingleObject(s->base.available, 20);
    }
    return 0;
}

static int playback(const wchar_t *path, double start_ms, double end_ms, int device_index, double bpm)
{
    playback_state s; ma_device device; ma_context context;
    ma_device_info *inputs, *outputs; ma_uint32 input_count, output_count;
    ma_decoder_config decoder_config = ma_decoder_config_init(ma_format_f32, 2, SAMPLE_RATE);
    ma_device_config device_config = ma_device_config_init(ma_device_type_playback);
    ma_uint64 length = 0; HANDLE worker = NULL, control = NULL;
    int result = 0, device_initialized = 0, decoder_initialized = 0, context_initialized = 0;
    memset(&s, 0, sizeof(s));
    s.base.available = CreateEventW(NULL, FALSE, FALSE, NULL); s.base.stop_event = CreateEventW(NULL, TRUE, FALSE, NULL);
    s.base.queue = (float *)calloc(2 * QUEUE_CAPACITY, sizeof(float));
    if (!s.base.available || !s.base.stop_event || !s.base.queue) { error_line("PLAYBACK_INIT_FAILED", "Could not allocate local playback buffers."); result = 2; goto done; }
    s.metronome_bpm = bpm;
    if (bpm > 0) { s.source_start = (ma_uint64)floor(start_ms * 48); s.source_end = UINT64_MAX; }
    else {
        if (ma_decoder_init_file_w(path, &decoder_config, &s.decoder) != MA_SUCCESS) { error_line("PLAYBACK_OPEN_FAILED", "Could not decode the local playback WAV."); result = 2; goto done; }
        decoder_initialized = 1;
        if (ma_decoder_get_length_in_pcm_frames(&s.decoder, &length) != MA_SUCCESS) { error_line("PLAYBACK_LENGTH_FAILED", "Could not read the WAV duration."); result = 2; goto done; }
        s.source_start = (ma_uint64)floor(start_ms * 48); s.source_end = end_ms < 0 ? length : (ma_uint64)floor(end_ms * 48);
        if (s.source_start >= length || s.source_end <= s.source_start || s.source_end > length ||
            ma_decoder_seek_to_pcm_frame(&s.decoder, s.source_start) != MA_SUCCESS) {
            error_line("PLAYBACK_RANGE_INVALID", "The requested playback range is outside the WAV recording."); result = 2; goto done;
        }
    }
    if (ma_context_init(NULL, 0, NULL, &context) != MA_SUCCESS) { error_line("DEVICE_CONTEXT_FAILED", "Could not initialize Windows playback."); result = 2; goto done; }
    context_initialized = 1;
    if (ma_context_get_devices(&context, &outputs, &output_count, &inputs, &input_count) != MA_SUCCESS || device_index >= (int)output_count) {
        error_line("DEVICE_SELECTION_FAILED", "The selected playback device is unavailable."); result = 2; goto done;
    }
    if (device_index >= 0) device_config.playback.pDeviceID = &outputs[device_index].id;
    device_config.playback.format = ma_format_f32; device_config.playback.channels = 2;
    device_config.sampleRate = SAMPLE_RATE; device_config.periodSizeInFrames = HOP;
    device_config.dataCallback = playback_callback; device_config.notificationCallback = playback_notification; device_config.pUserData = &s;
    if (ma_device_init(&context, &device_config, &device) != MA_SUCCESS) { error_line("PLAYBACK_DEVICE_FAILED", "Could not open the Windows playback device."); result = 2; goto done; }
    device_initialized = 1;
    while (s.decoded < 16384 && !InterlockedCompareExchange(&s.decoder_done, 0, 0)) if (!playback_fill(&s)) break;
    if (s.base.fatal) { result = 3; goto done; }
    worker = CreateThread(NULL, 0, playback_worker, &s, 0, NULL);
    if (!worker || ma_device_start(&device) != MA_SUCCESS) { error_line("PLAYBACK_START_FAILED", "Could not start Windows playback."); result = 2; goto done; }
    if (bpm > 0) printf("{\"type\":\"ready\",\"mode\":\"metronome\",\"sampleRate\":48000,\"timeMs\":0,\"bpm\":%.6f,\"startMs\":%.6f,\"endMs\":null}\n", bpm, (double)s.source_start / 48);
    else printf("{\"type\":\"ready\",\"mode\":\"playback\",\"sampleRate\":48000,\"timeMs\":0,\"startMs\":%.6f,\"endMs\":%.6f}\n", (double)s.source_start / 48, (double)s.source_end / 48);
    fflush(stdout);
    InterlockedExchange(&s.base.ready, 1);
    control = CreateThread(NULL, 0, stdin_worker, &s.base, 0, NULL);
    if (!control) { error_line("CONTROL_START_FAILED", "Could not start playback STOP control."); result = 2; goto done; }
    WaitForSingleObject(s.base.stop_event, INFINITE);
done:
    InterlockedExchange(&s.base.stopping, 1);
    if (device_initialized) ma_device_uninit(&device);
    if (s.base.available) SetEvent(s.base.available);
    if (worker) { WaitForSingleObject(worker, INFINITE); CloseHandle(worker); }
    if (control) { CancelSynchronousIo(control); WaitForSingleObject(control, 2000); CloseHandle(control); }
    if (s.base.fatal == 1) { error_line("PLAYBACK_UNDERRUN", "Playback stopped because decoded audio could not keep up."); result = 3; }
    if (s.base.fatal == 2) { error_line("PLAYBACK_DECODE_FAILED", "Playback stopped because WAV decoding failed."); result = 3; }
    if (s.base.fatal == 3) { error_line("PLAYBACK_DEVICE_STOPPED", "The Windows playback device stopped unexpectedly."); result = 3; }
    if (decoder_initialized) ma_decoder_uninit(&s.decoder);
    if (context_initialized) ma_context_uninit(&context);
    if (result == 0) stopped_line((uint64_t)InterlockedCompareExchange64(&s.base.read_index, 0, 0));
    if (s.base.available) CloseHandle(s.base.available);
    if (s.base.stop_event) CloseHandle(s.base.stop_event);
    free(s.base.queue); return result;
}

static int number(const wchar_t *text, double *value)
{
    wchar_t *end = NULL;
    *value = wcstod(text, &end);
    return end != text && *end == 0 && isfinite(*value);
}

int wmain(int argc, wchar_t **argv)
{
    capture_state state;
    const wchar_t *analyze_path = NULL, *record_path = NULL, *play_path = NULL;
    double minimum = 27.5, maximum = 4200, window = 4096, a4 = 440, start_ms = 0, end_ms = -1;
    double capture_index = -1, playback_index = -1, bpm = 0;
    int loopback = 0;
    int i, result;
    memset(&state, 0, sizeof(state));
    for (i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--help") == 0) {
            fprintf(stderr, "NoteLiteAudio [--min-frequency Hz] [--max-frequency Hz] [--window 1024|2048|4096|8192|16384] [--a4 Hz] [--record ABSOLUTE.wav] [--analyze INPUT.wav] [--capture-device INDEX] [--loopback]\nNoteLiteAudio --play ABS.wav [--start-ms 0] [--end-ms MS] [--playback-device INDEX]\nNoteLiteAudio --metronome BPM [--playback-device INDEX]\nNoteLiteAudio --list-devices\nstdin: STOP or EOF. stdout: NDJSON ready, pitch frames, unified note/uncertainty events, stopped.\n"); return 0;
        }
        if (wcscmp(argv[i], L"--version") == 0) { puts("NoteLiteAudio 1; miniaudio 0.11.25; native MPM/YIN"); return 0; }
        if (wcscmp(argv[i], L"--list-devices") == 0) return list_devices();
        if (wcscmp(argv[i], L"--loopback") == 0) { loopback = 1; continue; }
        if (i + 1 >= argc) { error_line("INVALID_ARGUMENT", "Missing command line argument value."); return 2; }
        if (wcscmp(argv[i], L"--min-frequency") == 0) { if (!number(argv[++i], &minimum)) goto argument_error; }
        else if (wcscmp(argv[i], L"--max-frequency") == 0) { if (!number(argv[++i], &maximum)) goto argument_error; }
        else if (wcscmp(argv[i], L"--window") == 0) { if (!number(argv[++i], &window)) goto argument_error; }
        else if (wcscmp(argv[i], L"--a4") == 0) { if (!number(argv[++i], &a4) || a4 < 415 || a4 > 466) goto argument_error; }
        else if (wcscmp(argv[i], L"--record") == 0) record_path = argv[++i];
        else if (wcscmp(argv[i], L"--analyze") == 0) analyze_path = argv[++i];
        else if (wcscmp(argv[i], L"--play") == 0) play_path = argv[++i];
        else if (wcscmp(argv[i], L"--metronome") == 0) { if (!number(argv[++i], &bpm) || bpm < 20 || bpm > 400) goto argument_error; }
        else if (wcscmp(argv[i], L"--start-ms") == 0) { if (!number(argv[++i], &start_ms) || start_ms < 0 || start_ms > 100000000) goto argument_error; }
        else if (wcscmp(argv[i], L"--end-ms") == 0) { if (!number(argv[++i], &end_ms) || end_ms < 0 || end_ms > 100000000) goto argument_error; }
        else if (wcscmp(argv[i], L"--capture-device") == 0) { if (!number(argv[++i], &capture_index) || capture_index < 0 || capture_index > 10000 || capture_index != floor(capture_index)) goto argument_error; }
        else if (wcscmp(argv[i], L"--playback-device") == 0) { if (!number(argv[++i], &playback_index) || playback_index < 0 || playback_index > 10000 || playback_index != floor(playback_index)) goto argument_error; }
        else goto argument_error;
    }
    if (play_path || bpm > 0) {
        if (analyze_path || record_path || loopback || (play_path && bpm > 0) || (bpm > 0 && end_ms >= 0)) goto argument_error;
        return playback(play_path, start_ms, end_ms, (int)playback_index, bpm);
    }
    if (window < 1024 || window > 16384 || window != floor(window) ||
        !nl_pitch_init(&state.pitch, (size_t)window, HOP, SAMPLE_RATE, minimum, maximum)) {
        error_line("INVALID_CONFIG", "Invalid frequency range/window: use a power of two and at least 1.33 periods of the minimum frequency."); return 2;
    }
    if (record_path) {
        ma_encoder_config config = ma_encoder_config_init(ma_encoding_format_wav, ma_format_s16, 1, SAMPLE_RATE);
        /* Absolute paths prevent output being written into an unexpected launch directory. */
        if (!(wcslen(record_path) > 2 && ((record_path[1] == L':' && (record_path[2] == L'\\' || record_path[2] == L'/')) ||
            (record_path[0] == L'\\' && record_path[1] == L'\\')))) {
            error_line("INVALID_RECORD_PATH", "Recording requires an absolute Windows WAV path."); nl_pitch_free(&state.pitch); return 2;
        }
        if (ma_encoder_init_file_w(record_path, &config, &state.recorder) != MA_SUCCESS) {
            error_line("RECORD_OPEN_FAILED", "Could not create the local WAV recording."); nl_pitch_free(&state.pitch); return 2;
        }
        state.recording = 1;
    }
    nl_events_init(&state.events, a4);
    result = analyze_path ? offline(&state, analyze_path) : live(&state, (int)capture_index, (int)playback_index, loopback);
    if (state.ready) nl_events_finish(&state.events, state.consumed, SAMPLE_RATE);
    if (state.recording) ma_encoder_uninit(&state.recorder);
    if (state.ready) stopped_line(state.consumed);
    nl_pitch_free(&state.pitch); return result;
argument_error:
    error_line("INVALID_ARGUMENT", "Unknown or invalid command line argument."); return 2;
}
