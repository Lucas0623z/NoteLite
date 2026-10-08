"""Continuous pitch refinement from recorded audio around detected AMT notes.

This does not inspect the score. Basic Pitch supplies the detected MIDI attack;
local spectral interpolation refines its coarse 1/3-semitone contour estimate.
Ambiguous/weak spectra retain the original estimate and are marked coarse.
"""
import math
import numpy as np


def refine(notes, path, a4):
    import soundfile
    signal, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    signal = signal.mean(axis=1)
    size = 8192 if rate <= 48000 else 16384
    window = np.hanning(size)
    cache = {}
    for note in notes:
        nominal = 440*2**((note.get("modelMidi",note["midi"]+(12*math.log2(a4/440)))-69)/12)
        estimates = []
        for fraction in (.25, .5, .75):
            center = round((note["onset"]+note["duration"]*fraction)*rate)
            center = max(size//2, min(len(signal)-size//2, center))
            if center not in cache:
                low, high = center-size//2, center+size//2
                if low < 0 or high > len(signal):
                    continue
                cache[center] = np.abs(np.fft.rfft(signal[low:high]*window))
                if len(cache) > 128:
                    del cache[next(iter(cache))]
            spectrum = cache[center]
            low = max(1, math.floor(nominal*2**(-.65/12)*size/rate))
            high = min(len(spectrum)-2, math.ceil(nominal*2**(.65/12)*size/rate))
            if high <= low:
                continue
            index = low+int(np.argmax(spectrum[low:high+1]))
            # Require a clear local maximum and prominence above the surrounding
            # spectrum; overlapping voices and noisy attacks may be unresolved.
            if not low < index < high or spectrum[index] < max(spectrum[index-1], spectrum[index+1]):
                continue
            neighborhood = spectrum[max(1,index-8):min(len(spectrum),index+9)]
            if spectrum[index] < 4*max(float(np.median(neighborhood)),1e-9):
                continue
            left, middle, right = np.log(np.maximum(spectrum[index-1:index+2], 1e-12))
            denominator = left-2*middle+right
            shift = .5*(left-right)/denominator if abs(denominator) > 1e-12 else 0
            frequency = (index+np.clip(shift,-.5,.5))*rate/size
            estimates.append(float(frequency))
        if len(estimates) >= 2:
            pitch = 69+12*math.log2(float(np.median(estimates))/a4)
            if abs(pitch-(69+12*math.log2(nominal/a4))) <= .65:
                note["modelCents"] = note["cents"]
                pitch_samples = 6900+1200*np.log2(np.asarray(estimates)/a4)
                spread = float(np.median(np.abs(pitch_samples-np.median(pitch_samples))))
                note.update(midi=round(pitch),cents=round((pitch-round(pitch))*100,3),pitchCents=round(pitch*100,3),
                            frequency=round(float(np.median(estimates)),6),pitchSource="spectral-refinement",centsReliability="spectral-estimate",
                            centsSampleCount=len(estimates),centsSpread=round(spread,3),centsSpreadStatistic="mad")
                continue
        note.update(pitchSource="basic-pitch-contour",centsResolution=100/3,centsReliability="coarse-contour",
                    centsSampleCount=len(note.get("pitchBendCents",[])))
    return notes
