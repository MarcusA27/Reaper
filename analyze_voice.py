"""
analyze_voice.py — measure the objective fingerprint of a voice clip.

Gates to voiced frames (drops silence), then reports pitch, brightness,
spectral tilt, band-energy distribution, and resonance peaks so an effect
chain can be tuned to MATCH a target instead of guessed by ear.

    python3 analyze_voice.py file1.wav [file2.wav ...]
"""

import sys
import wave
from pathlib import Path

import numpy as np


def load(path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def voiced_frames(x, sr, frame=2048, hop=1024):
    n = 1 + (len(x) - frame) // hop
    frames = np.stack([x[i * hop:i * hop + frame] for i in range(n)])
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    thresh = max(rms.max() * 0.15, np.median(rms) * 1.5)
    return frames[rms > thresh]


def estimate_f0(frames, sr, fmin=70, fmax=400):
    f0s = []
    lo, hi = int(sr / fmax), int(sr / fmin)
    for fr in frames:
        fr = fr - fr.mean()
        if np.sqrt((fr ** 2).mean()) < 1e-4:
            continue
        ac = np.correlate(fr, fr, "full")[len(fr) - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if len(seg) == 0:
            continue
        lag = lo + np.argmax(seg)
        if ac[lag] / ac[0] > 0.3:
            f0s.append(sr / lag)
    return np.median(f0s) if f0s else float("nan")


def ltas(frames):
    win = np.hanning(frames.shape[1])
    spec = np.abs(np.fft.rfft(frames * win, axis=1))
    return spec.mean(axis=0)


def analyze(path):
    x, sr = load(path)
    frames = voiced_frames(x, sr)
    if len(frames) == 0:
        print(f"{Path(path).name}: no voiced frames found")
        return
    freqs = np.fft.rfftfreq(frames.shape[1], 1 / sr)
    avg = ltas(frames)
    avg_db = 20 * np.log10(avg + 1e-9)

    centroid = (freqs * avg).sum() / avg.sum()

    # spectral flatness in the voice band: grit/noisiness, 0=tonal .. 1=noisy
    win = np.hanning(frames.shape[1])
    p = np.abs(np.fft.rfft(frames * win, axis=1)) ** 2 + 1e-12
    band_m = (freqs >= 200) & (freqs < 6000)
    pb = p[:, band_m]
    flat = np.exp(np.log(pb).mean(axis=1)) / pb.mean(axis=1)
    flatness = float(np.median(flat))

    def band(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        return avg[m].sum()
    bands = {"sub<200": band(0, 200), "low.2-1k": band(200, 1000),
             "mid1-4k": band(1000, 4000), "hi4-8k": band(4000, 8000),
             "air8k+": band(8000, sr / 2)}
    tot = sum(bands.values())

    # resonance peaks: smooth LTAS, find local maxima above the trend
    k = 9
    smooth = np.convolve(avg_db, np.ones(k) / k, "same")
    peaks = []
    for i in range(2, len(smooth) - 2):
        if smooth[i] > smooth[i - 1] and smooth[i] > smooth[i + 1] and freqs[i] < 8000:
            peaks.append((freqs[i], smooth[i]))
    peaks.sort(key=lambda t: -t[1])
    top = sorted(p[0] for p in peaks[:5])

    f0 = estimate_f0(frames, sr)

    # dominant spectral comb spacing (Hz) via cepstrum of the LTAS:
    # a periodic ripple in the spectrum (ring-mod / comb) shows as a cepstral peak.
    logspec = np.log(avg + 1e-9)
    ceps = np.abs(np.fft.rfft(logspec - logspec.mean()))
    df = freqs[1] - freqs[0]
    q = np.fft.rfftfreq(len(logspec), df)          # quefrency in "1/Hz" -> period in Hz
    valid = (q > 1 / 800.0) & (q < 1 / 40.0)        # look for spacing 40-800 Hz
    spacing = 1.0 / q[valid][np.argmax(ceps[valid])] if valid.any() else float("nan")

    print(f"\n=== {Path(path).name} ===")
    print(f"  sr={sr}  voiced_frames={len(frames)}")
    print(f"  pitch F0       : {f0:6.1f} Hz")
    print(f"  spectral centroid (brightness): {centroid:6.0f} Hz")
    print(f"  spectral flatness (grit 0-1)  : {flatness:6.3f}")
    print(f"  band energy %  : " + "  ".join(f"{k}={100*v/tot:4.1f}" for k, v in bands.items()))
    print(f"  top resonances : " + ", ".join(f"{f:.0f}Hz" for f in top))
    print(f"  comb/mod spacing: {spacing:6.1f} Hz")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
