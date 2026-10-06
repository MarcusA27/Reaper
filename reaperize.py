"""
reaperize.py

Run a clean TTS clip through an effect chain to push it toward the
"Reaper" (Black Ops 3 specialist) sound: deep, synthetic, metallic, menacing.

Pure local DSP — no API key, no network. Operates on the WAVs that
generate_reaper_clips.py produced (44.1kHz / 16-bit / mono).

Usage:
    python3 reaperize.py                          # process reaper_clips/boot_01.wav -> boot_01_reaper.wav
    python3 reaperize.py path/to/clip.wav         # process one named file
    python3 reaperize.py --batch                  # process every *.wav in reaper_clips/ (skips *_reaper.wav)

Tune the sound by editing PARAMS below, then re-run on the single test clip.
"""

import argparse
import wave
from pathlib import Path

import numpy as np
from scipy import signal

OUT_DIR = Path("reaper_clips")
SUFFIX = "_reaper"

# ---- the sound, as knobs. tune these, re-run on one clip, listen. ----
# COMMITTED = "M1_light": vocoder robot core + clean radio/comms band + foldback
# grit, de-mudded. The Reaper voice. Edit to retune; batch with --batch.
PARAMS = {
    "pitch_semitones": 0.0,     # natural TTS pitch — synthesis does the inhuman work
    "highpass_hz": 380,         # comms low edge (also cuts mud)
    "filter_order": 6,          # steep radio-band edges
    "shaper": "fold",           # violent foldback waveshaping
    "drive": 4.0,               # waveshaping grit
    "drive_mix": 0.9,
    "bitcrush_bits": 8,         # digital crunch ("some")
    "bitcrush_downsample": 2,
    "bitcrush_mix": 0.4,
    "formant_ratio": 0.9,       # <1 lowers formants (bigger/darker timbre, pitch unchanged)
    "comb_delay_ms": 2.0,       # metallic ring body
    "comb_feedback": 0.85,
    "comb_mix": 0.4,
    "ringmod_hz": 65.0,         # 65Hz metallic buzz
    "ringmod_mix": 0.4,
    "chorus_depth_ms": 4.0,     # detune doubling
    "chorus_rate_hz": 0.5,
    "chorus_mix": 0.22,
    "chorus_voices": 2,
    "presence_hz": 2000.0,      # comms bite / clarity
    "presence_gain_db": 6.0,
    "presence_q": 1.0,
    "highshelf_hz": 5000.0,
    "highshelf_db": 0.0,        # OFF
    "lowpass_hz": 3400,         # radio-band high edge
    # --- war-machine weight (off) ---
    "suboct_mix": 0.0,
    "suboct_lowpass": 700,
    "suboct_drive": 3.0,
    "body_hz": 300.0,           # low-mid de-mud notch
    "body_gain_db": -3.0,
    "body_q": 0.9,
    # --- radio/comms ---
    "comp_threshold": 0.3,      # compressor: flat, in-your-face radio presence
    "comp_ratio": 4.0,
    "comp_mix": 0.6,
    "noise_mix": 0.0,           # static/hiss bed (0 = off)
    "noise_follow": 0.7,
    # --- synthetic / robotic core ---
    "vocoder_mix": 0.85,        # talking-synth robot timbre — THE character
    "vocoder_bands": 22,        # more bands = more intelligible, fewer = more robotic
    "vocoder_carrier": "saw",   # "saw" buzzy robot | "noise" whisper robot
    "vocoder_freq": 100.0,      # carrier pitch -> monotone robot pitch
    "vocoder_lo": 200.0,        # low edge of vocoder band (de-mudded)
    "harm_semitones": 0.0,      # harmonized layer interval (off)
    "harm_mix": 0.0,
    "reverb_mix": 0.0,          # metallic chassis/helmet space (off)
    "reverb_decay": 0.8,
    # --- sibilance restore (fixes vocoder "s -> th" lisp) ---
    "sib_mix": 0.0,             # blend dry-voice highs back in for crisp s's (0 = off)
    "sib_hz": 4500.0,           # only frequencies above this (the sibilant band)
    "peak_dbfs": -1.0,          # final normalize ceiling
}


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    x = np.clip(x, -1.0, 1.0)
    pcm = (x * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ---- phase-vocoder pitch shift (lower pitch, keep duration) ----
def _stft(y, n_fft, hop):
    window = np.hanning(n_fft + 1)[:-1]
    y = np.pad(y, n_fft // 2, mode="reflect")
    n_frames = 1 + (len(y) - n_fft) // hop
    frames = np.stack([y[i * hop:i * hop + n_fft] * window for i in range(n_frames)], axis=1)
    return np.fft.rfft(frames, axis=0)


def _istft(D, hop):
    n_fft = 2 * (D.shape[0] - 1)
    window = np.hanning(n_fft + 1)[:-1]
    frames = np.fft.irfft(D, axis=0)
    n_frames = D.shape[1]
    y = np.zeros(n_fft + hop * (n_frames - 1))
    wsum = np.zeros_like(y)
    for i in range(n_frames):
        y[i * hop:i * hop + n_fft] += frames[:, i] * window
        wsum[i * hop:i * hop + n_fft] += window ** 2
    wsum[wsum < 1e-8] = 1e-8
    y /= wsum
    return y[n_fft // 2:-(n_fft // 2)]


def _phase_vocoder(D, rate, hop):
    steps = np.arange(0, D.shape[1], rate)
    out = np.zeros((D.shape[0], len(steps)), dtype=complex)
    phase_adv = np.linspace(0, np.pi * hop, D.shape[0])
    phase_acc = np.angle(D[:, 0])
    D = np.pad(D, [(0, 0), (0, 2)], mode="constant")
    for t, step in enumerate(steps):
        i = int(step)
        frac = step - i
        cols = D[:, i:i + 2]
        mag = (1 - frac) * np.abs(cols[:, 0]) + frac * np.abs(cols[:, 1])
        out[:, t] = mag * np.exp(1j * phase_acc)
        dphase = np.angle(cols[:, 1]) - np.angle(cols[:, 0]) - phase_adv
        dphase -= 2 * np.pi * np.round(dphase / (2 * np.pi))
        phase_acc += phase_adv + dphase
    return out


def pitch_shift(x, semitones, n_fft=2048, hop=512):
    if semitones == 0:
        return x
    rate = 2.0 ** (-semitones / 12.0)          # >1 for downward shift
    stretched = _istft(_phase_vocoder(_stft(x, n_fft, hop), rate, hop), hop)
    n_out = int(round(len(stretched) * rate))
    return signal.resample(stretched, n_out)


def formant_shift(x, ratio, n_fft=1024, hop=256, lifter=24):
    # Shift the spectral envelope (formants) by `ratio` while leaving pitch alone.
    # ratio < 1 lowers formants -> bigger/darker timbre. Source-filter via cepstrum.
    if ratio == 1.0:
        return x
    D = _stft(x, n_fft, hop)
    logmag = np.log(np.abs(D) + 1e-9)
    phase = np.angle(D)
    nbins = logmag.shape[0]
    full = np.concatenate([logmag, logmag[-2:0:-1]], axis=0)     # mirror to full spectrum
    ceps = np.real(np.fft.ifft(full, axis=0))
    win = np.zeros(ceps.shape[0])
    win[:lifter] = 1.0
    win[-lifter + 1:] = 1.0
    env = np.real(np.fft.fft(ceps * win[:, None], axis=0))[:nbins]   # smooth log envelope
    idx = np.arange(nbins) / ratio                              # resample envelope: env[f/ratio]
    i0 = np.clip(np.floor(idx).astype(int), 0, nbins - 1)
    i1 = np.clip(i0 + 1, 0, nbins - 1)
    frac = (idx - np.floor(idx))[:, None]
    new_env = (1 - frac) * env[i0] + frac * env[i1]
    new_mag = np.exp(logmag - env + new_env)
    return _istft(new_mag * np.exp(1j * phase), hop)


# ---- the rest of the chain ----
def butter_filter(x, sr, cutoff, btype, order=4):
    sos = signal.butter(order, cutoff / (sr / 2), btype=btype, output="sos")
    return signal.sosfilt(sos, x)


def compress(x, sr, threshold, ratio, mix):
    win = max(1, int(sr * 0.005))
    env = np.sqrt(np.convolve(x ** 2, np.ones(win) / win, "same") + 1e-9)
    gain = np.ones_like(x)
    over = env > threshold
    gain[over] = (threshold + (env[over] - threshold) / ratio) / env[over]
    wet = x * gain
    return (1 - mix) * x + mix * wet


def add_noise(x, sr, mix, follow):
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(len(x))
    win = max(1, int(sr * 0.005))
    env = np.convolve(np.abs(x), np.ones(win) / win, "same")
    env /= env.max() + 1e-9
    gain = follow * env + (1 - follow)
    return x + mix * noise * gain


def peaking_eq(x, sr, f0, gain_db, q):
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    cos = np.cos(w0)
    b = [1 + alpha * a, -2 * cos, 1 - alpha * a]
    a_ = [1 + alpha / a, -2 * cos, 1 - alpha / a]
    return signal.lfilter(b, a_, x)


def high_shelf(x, sr, f0, gain_db):
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / sr
    cos, sin = np.cos(w0), np.sin(w0)
    alpha = sin / 2 * np.sqrt((a + 1 / a) * (1 / 0.9 - 1) + 2)
    sa = 2 * np.sqrt(a) * alpha
    b = [a * ((a + 1) + (a - 1) * cos + sa),
         -2 * a * ((a - 1) + (a + 1) * cos),
         a * ((a + 1) + (a - 1) * cos - sa)]
    a_ = [(a + 1) - (a - 1) * cos + sa,
          2 * ((a - 1) - (a + 1) * cos),
          (a + 1) - (a - 1) * cos - sa]
    return signal.lfilter(b, a_, x)


def comb_resonator(x, sr, delay_ms, feedback, mix):
    d = max(1, int(round(delay_ms * sr / 1000.0)))
    a = np.zeros(d + 1)
    a[0] = 1.0
    a[d] = -feedback
    wet = signal.lfilter([1.0 - feedback], a, x)   # gain-compensated feedback comb
    return (1 - mix) * x + mix * wet


def shape(x, drive, mix, kind):
    if kind == "hardclip":
        wet = np.clip(drive * x, -1.0, 1.0)
    elif kind == "fold":                       # triangle foldback: violent, metallic, inharmonic
        y = drive * x
        wet = np.abs(((y - 1.0) % 4.0) - 2.0) - 1.0
    else:                                      # "tanh" — gentle saturation
        wet = np.tanh(drive * x) / np.tanh(drive)
    return (1 - mix) * x + mix * wet


def bitcrush(x, bits, downsample, mix):
    wet = x
    if bits < 16:
        levels = 2 ** bits
        wet = np.round(wet * (levels / 2)) / (levels / 2)
    if downsample > 1:
        idx = (np.arange(len(wet)) // downsample) * downsample
        wet = wet[idx]
    return (1 - mix) * x + mix * wet


def vocoder(x, sr, bands, carrier, freq, mix, lo=150.0, hi=5000.0):  # raise lo to de-mud
    t = np.arange(len(x)) / sr
    if carrier == "noise":
        car = np.random.default_rng(0).standard_normal(len(x))
    else:                                          # harmonically rich sawtooth -> classic robot
        car = signal.sawtooth(2 * np.pi * freq * t)
    edges = np.logspace(np.log10(lo), np.log10(hi), bands + 1)
    env_sos = signal.butter(2, 25 / (sr / 2), "low", output="sos")
    out = np.zeros_like(x)
    for i in range(bands):
        sos = signal.butter(2, [edges[i] / (sr / 2), edges[i + 1] / (sr / 2)],
                            "bandpass", output="sos")
        env = signal.sosfilt(env_sos, np.abs(signal.sosfilt(sos, x)))
        out += signal.sosfilt(sos, car) * env
    out *= np.sqrt((x ** 2).mean() / ((out ** 2).mean() + 1e-9))   # match level
    return (1 - mix) * x + mix * out


def harmonize(x, sr, semitones, mix):
    h = pitch_shift(x, semitones)
    n = min(len(x), len(h))
    y = x.copy()
    y[:n] = y[:n] + mix * h[:n]
    return y


def metallic_reverb(x, sr, mix, decay):
    delays_ms = [13.7, 17.3, 19.1, 23.3]           # short prime-ish delays -> metallic ring
    wet = np.zeros_like(x)
    for dm in delays_ms:
        d = max(1, int(dm * sr / 1000.0))
        a = np.zeros(d + 1)
        a[0] = 1.0
        a[d] = -decay
        wet += signal.lfilter([1.0 - decay], a, x)
    wet /= len(delays_ms)
    return (1 - mix) * x + mix * wet


def ring_mod(x, sr, freq, mix):
    t = np.arange(len(x)) / sr
    carrier = np.sin(2 * np.pi * freq * t)
    return (1 - mix) * x + mix * (x * carrier)


def chorus(x, sr, depth_ms, rate_hz, mix, voices):
    n = len(x)
    t = np.arange(n)
    base = 15.0
    wet = np.zeros(n)
    for v in range(voices):
        delay_ms = base + depth_ms * np.sin(2 * np.pi * rate_hz * (t / sr) + v * 2 * np.pi / voices)
        idx = t - delay_ms * sr / 1000.0
        idx = np.clip(idx, 0, n - 1)
        i0 = np.floor(idx).astype(int)
        frac = idx - i0
        i1 = np.clip(i0 + 1, 0, n - 1)
        wet += (1 - frac) * x[i0] + frac * x[i1]
    wet /= max(voices, 1)
    return (1 - mix) * x + mix * wet


def reaperize(x, sr, p):
    order = p["filter_order"]
    x = pitch_shift(x, p["pitch_semitones"])
    voice = x.copy()                                         # source for the sub-octave layer
    x = butter_filter(x, sr, p["highpass_hz"], "highpass", order)
    if p["harm_mix"] > 0:
        x = harmonize(x, sr, p["harm_semitones"], p["harm_mix"])
    if p["vocoder_mix"] > 0:
        x = vocoder(x, sr, p["vocoder_bands"], p["vocoder_carrier"], p["vocoder_freq"],
                    p["vocoder_mix"], lo=p["vocoder_lo"])
    if p["formant_ratio"] != 1.0:
        x = formant_shift(x, p["formant_ratio"])
    x = comb_resonator(x, sr, p["comb_delay_ms"], p["comb_feedback"], p["comb_mix"])
    x = shape(x, p["drive"], p["drive_mix"], p["shaper"])
    x = bitcrush(x, p["bitcrush_bits"], p["bitcrush_downsample"], p["bitcrush_mix"])
    x = chorus(x, sr, p["chorus_depth_ms"], p["chorus_rate_hz"], p["chorus_mix"], p["chorus_voices"])
    if p["body_gain_db"] != 0:
        x = peaking_eq(x, sr, p["body_hz"], p["body_gain_db"], p["body_q"])
    x = peaking_eq(x, sr, p["presence_hz"], p["presence_gain_db"], p["presence_q"])
    x = high_shelf(x, sr, p["highshelf_hz"], p["highshelf_db"])
    if p["noise_mix"] > 0:
        x = add_noise(x, sr, p["noise_mix"], p["noise_follow"])
    if p["comp_mix"] > 0:
        x = compress(x, sr, p["comp_threshold"], p["comp_ratio"], p["comp_mix"])
    x = butter_filter(x, sr, p["lowpass_hz"], "lowpass", order)
    x = ring_mod(x, sr, p["ringmod_hz"], p["ringmod_mix"])   # 65Hz buzz LAST so nothing smears it
    if p["sib_mix"] > 0:                                     # restore crisp s's past the lowpass
        sib = butter_filter(voice, sr, p["sib_hz"], "highpass", 4)
        n = min(len(x), len(sib))
        x = x[:n] + p["sib_mix"] * sib[:n]
    if p["reverb_mix"] > 0:
        x = metallic_reverb(x, sr, p["reverb_mix"], p["reverb_decay"])

    if p["suboct_mix"] > 0:                                  # mechanical octave-down growl
        sub = pitch_shift(voice, -12.0)
        sub = shape(sub, p["suboct_drive"], 0.9, "fold")
        sub = butter_filter(sub, sr, p["suboct_lowpass"], "lowpass")
        n = min(len(x), len(sub))
        x = x[:n] + p["suboct_mix"] * sub[:n]

    peak = np.max(np.abs(x))
    if peak > 0:
        x *= (10 ** (p["peak_dbfs"] / 20.0)) / peak
    return x


def process(in_path):
    out_path = in_path.with_name(in_path.stem + SUFFIX + ".wav")
    x, sr = read_wav(in_path)
    y = reaperize(x, sr, PARAMS)
    write_wav(out_path, y, sr)
    print(f"  {in_path.name}  ->  {out_path.name}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Push a TTS clip toward the Reaper voice.")
    parser.add_argument("file", nargs="?", default=str(OUT_DIR / "boot_01.wav"),
                        help="WAV to process (default: reaper_clips/boot_01.wav)")
    parser.add_argument("--batch", action="store_true",
                        help="Process every clip in reaper_clips/ (skips already-processed ones).")
    args = parser.parse_args()

    if args.batch:
        clips = sorted(c for c in OUT_DIR.glob("*.wav") if not c.stem.endswith(SUFFIX))
        if not clips:
            raise SystemExit(f"No clips found in {OUT_DIR}/. Run generate_reaper_clips.py first.")
        for c in clips:
            process(c)
        print(f"\nDone. {len(clips)} clips processed.")
    else:
        in_path = Path(args.file)
        if not in_path.exists():
            raise SystemExit(f"{in_path} not found.")
        process(in_path)


if __name__ == "__main__":
    main()
