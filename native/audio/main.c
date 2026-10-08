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

#define MA_NO_PLAYBACK
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
    printf("{\"frequency\":%.8f,\"clarity\":%.6f,\"rms\":%.8f,\"timeMs\":%.6f,\"onset\":%s,\"sampleCount\":%llu,\"onsetTimeMs\":%s,\"pitchTimeMs\":%.6f}\n",
        f->frequency, f->clarity, f->rms, f->time_ms,
        f->onset ? "true" : "false", (unsigned long long)f->sample_count,
        onset_time, f->pitch_time_ms);
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
        if (nl_pitch_push(&s->pitch, samples[i], &frame)) frame_line(&frame);
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

static int live(capture_state *s)
{
    ma_device device;
    ma_device_config config = ma_device_config_init(ma_device_type_capture);
    HANDLE worker = NULL, control = NULL;
    int result = 0;
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
    if (ma_device_init(NULL, &config, &device) != MA_SUCCESS) {
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
    free(s->queue); return result;
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
    const wchar_t *analyze_path = NULL, *record_path = NULL;
    double minimum = 27.5, maximum = 4200, window = 4096;
    int i, result;
    memset(&state, 0, sizeof(state));
    for (i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--help") == 0) {
            fprintf(stderr, "NoteLiteAudio [--min-frequency Hz] [--max-frequency Hz] [--window 1024|2048|4096|8192|16384] [--record ABSOLUTE.wav] [--analyze INPUT.wav]\nstdin: STOP or EOF. stdout: NDJSON ready, pitch frames, stopped; errors have type=error.\n"); return 0;
        }
        if (wcscmp(argv[i], L"--version") == 0) { puts("NoteLiteAudio 1; miniaudio 0.11.25; native MPM/YIN"); return 0; }
        if (i + 1 >= argc) { error_line("INVALID_ARGUMENT", "Missing command line argument value."); return 2; }
        if (wcscmp(argv[i], L"--min-frequency") == 0) { if (!number(argv[++i], &minimum)) goto argument_error; }
        else if (wcscmp(argv[i], L"--max-frequency") == 0) { if (!number(argv[++i], &maximum)) goto argument_error; }
        else if (wcscmp(argv[i], L"--window") == 0) { if (!number(argv[++i], &window)) goto argument_error; }
        else if (wcscmp(argv[i], L"--record") == 0) record_path = argv[++i];
        else if (wcscmp(argv[i], L"--analyze") == 0) analyze_path = argv[++i];
        else goto argument_error;
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
    result = analyze_path ? offline(&state, analyze_path) : live(&state);
    if (state.recording) ma_encoder_uninit(&state.recorder);
    if (state.ready) stopped_line(state.consumed);
    nl_pitch_free(&state.pitch); return result;
argument_error:
    error_line("INVALID_ARGUMENT", "Unknown or invalid command line argument."); return 2;
}
