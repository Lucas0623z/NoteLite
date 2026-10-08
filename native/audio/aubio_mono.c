/* Actual aubio 0.4.9 offline adapter. GPL-3.0-or-later when linked with aubio.
 * miniaudio handles local WAV decoding only; pitch/onset come from aubio. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <math.h>
#include <stdint.h>
#include "aubio.h"
#define MA_NO_DEVICE_IO
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#define MA_NO_ENGINE
#define MA_NO_GENERATION
#define MA_NO_MP3
#define MA_NO_FLAC
#define MINIAUDIO_IMPLEMENTATION
#include "vendor/miniaudio/miniaudio.h"

#define RATE 48000
#define HOP 480
#define MAX_ONSETS 500000u

int wmain(int argc, wchar_t **argv)
{
    const wchar_t *input = NULL, *output = NULL;
    double a4 = 440, minimum = 27.5, maximum = 4200, *onsets = NULL;
    uint_t window = 4096;
    uint64_t total = 0;
    size_t onset_count = 0;
    int i, status = 2, decoded = 0, comma = 0, output_created = 0;
    FILE *file = NULL;
    ma_decoder decoder;
    ma_decoder_config config = ma_decoder_config_init(ma_format_f32, 1, RATE);
    aubio_pitch_t *pitch = NULL;
    aubio_onset_t *onset = NULL;
    fvec_t *buffer = NULL, *frequency = NULL, *attack = NULL;
    for (i = 1; i < argc; ++i) {
        if (!wcscmp(argv[i], L"--version")) { puts("AubioMono 0.4.9 yinfast+complex"); return 0; }
        if (++i >= argc) { fputs("Missing option value.\n", stderr); return 2; }
        if (!wcscmp(argv[i-1], L"--input")) input = argv[i];
        else if (!wcscmp(argv[i-1], L"--output")) output = argv[i];
        else if (!wcscmp(argv[i-1], L"--a4")) {
            wchar_t *end; a4 = wcstod(argv[i], &end);
            if (*end || !isfinite(a4) || a4 < 400 || a4 > 480) return 2;
        } else if (!wcscmp(argv[i-1], L"--min-hz") || !wcscmp(argv[i-1], L"--max-hz")) {
            wchar_t *end; double value = wcstod(argv[i], &end);
            if (*end || !isfinite(value) || value < 20 || value > 10000) return 2;
            if (!wcscmp(argv[i-1], L"--min-hz")) minimum = value; else maximum = value;
        } else { fputs("Unknown option.\n", stderr); return 2; }
    }
    if (!input || !output || !_wcsicmp(input, output) || maximum <= minimum) { fputs("Use --input WAV --output JSON [--a4 Hz] [--min-hz 27.5] [--max-hz 4200].\n", stderr); return 2; }
    while (window < 4.0 * RATE / minimum && window < 16384) window *= 2;
    if (ma_decoder_init_file_w(input, &config, &decoder) != MA_SUCCESS) { fputs("Could not decode WAV.\n", stderr); goto done; }
    decoded = 1;
    pitch = new_aubio_pitch("yinfast", window, HOP, RATE);
    onset = new_aubio_onset("complex", window, HOP, RATE);
    buffer = new_fvec(HOP); frequency = new_fvec(1); attack = new_fvec(1);
    onsets = (double *)calloc(MAX_ONSETS, sizeof(double));
    if (!pitch || !onset || !buffer || !frequency || !attack || !onsets) { fputs("Could not allocate aubio detector.\n", stderr); goto done; }
    aubio_pitch_set_unit(pitch, "Hz"); aubio_pitch_set_silence(pitch, -60);
    aubio_onset_set_silence(onset, -60); aubio_onset_set_minioi_ms(onset, 80);
    file = _wfopen(output, L"wb");
    if (!file) { fputs("Could not write JSON.\n", stderr); goto done; }
    output_created = 1;
    fprintf(file, "{\"engine\":\"aubio\",\"version\":\"0.4.9\",\"algorithm\":\"yinfast+complex\",\"sampleRate\":48000,\"window\":%u,\"hop\":480,\"a4\":%.6f,\"minHz\":%.6f,\"maxHz\":%.6f,\"timeDefinition\":\"analysis window midpoint in input seconds\",\"frames\":[", window, a4, minimum, maximum);
    for (;;) {
        ma_uint64 count = 0;
        ma_result result = ma_decoder_read_pcm_frames(&decoder, buffer->data, HOP, &count);
        if (result != MA_SUCCESS && result != MA_AT_END) { fputs("WAV read failed.\n", stderr); goto done; }
        if (!count) break;
        if (count < HOP) memset(buffer->data + count, 0, (HOP - (size_t)count) * sizeof(smpl_t));
        total += count;
        aubio_pitch_do(pitch, buffer, frequency); aubio_onset_do(onset, buffer, attack);
        double hz = frequency->data[0], confidence = aubio_pitch_get_confidence(pitch);
        double time = ((double)total - window / 2.0) / RATE;
        if (!isfinite(hz) || hz < minimum || hz > maximum) { hz = 0; confidence = 0; }
        if (!isfinite(confidence) || confidence < 0) confidence = 0;
        if (confidence > 1) confidence = 1;
        if (time < 0) time = 0;
        fprintf(file, "%s{\"time\":%.8f,\"frequency\":%.8f,\"confidence\":%.8f}", comma ? "," : "", time, hz, confidence); comma = 1;
        if (attack->data[0] > 0) {
            if (onset_count == MAX_ONSETS) { fputs("Onset count limit exceeded.\n", stderr); goto done; }
            onsets[onset_count++] = aubio_onset_get_last_s(onset);
        }
        if (ferror(file)) { fputs("JSON write failed.\n", stderr); goto done; }
    }
    fprintf(file, "],\"onsets\":[");
    for (size_t n = 0; n < onset_count; ++n) fprintf(file, "%s%.8f", n ? "," : "", onsets[n]);
    fprintf(file, "],\"sampleCount\":%llu,\"duration\":%.8f}\n", (unsigned long long)total, (double)total / RATE);
    if (ferror(file)) { fputs("JSON write failed.\n", stderr); goto done; }
    status = 0;
done:
    if (file && fclose(file) != 0) status = 2;
    if (status && output_created) _wremove(output); /* Never leave partial JSON as success. */
    if (decoded) ma_decoder_uninit(&decoder);
    if (pitch) del_aubio_pitch(pitch);
    if (onset) del_aubio_onset(onset);
    if (buffer) del_fvec(buffer);
    if (frequency) del_fvec(frequency);
    if (attack) del_fvec(attack);
    free(onsets); aubio_cleanup(); return status;
}
