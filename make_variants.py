"""
make_variants.py — render several distinct takes on one clip for A/B audition.

Pick the closest to Reaper by ear, tell me the letter, and we refine from there.
    python3 make_variants.py [path/to/clip.wav]   # default: reaper_clips/boot_01.wav
"""

import sys
from copy import deepcopy
from pathlib import Path

from reaperize import PARAMS, reaperize, read_wav, write_wav

BASE = PARAMS

# Base = winning R1_clean (comms + foldback grit). Each variant adds ONE of the
# top-three synthetic effects so we can hear which one is "the thing".
R1 = {
    "pitch_semitones": 0.0, "shaper": "fold", "comb_feedback": 0.85,
    "drive": 3.0, "drive_mix": 0.9, "ringmod_mix": 0.4, "comb_mix": 0.4,
    "bitcrush_mix": 0.1,
    "highpass_hz": 300, "lowpass_hz": 3400, "filter_order": 6,
    "comp_mix": 0.6, "comp_ratio": 4.0, "noise_mix": 0.0,
    "presence_hz": 1800.0, "presence_gain_db": 5.0,
}
# Committed = M1_light + crunch + 0.9 formant. Sibilance ladder blends dry-voice
# highs back to fix the vocoder "s -> th" lisp. More = crisper s's, but too much
# reintroduces a clean/un-robotic top end.
VARIANTS = {
    "X0_off": {"sib_mix": 0.0},
    "X1_subtle": {"sib_mix": 0.15},
    "X2_clear": {"sib_mix": 0.3},
    "X3_crisp": {"sib_mix": 0.5},
}


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("reaper_clips/boot_01.wav")
    x, sr = read_wav(src)
    for name, overrides in VARIANTS.items():
        p = deepcopy(BASE)
        p.update(overrides)
        out = src.with_name(f"{src.stem}__{name}.wav")
        write_wav(out, reaperize(x, sr, p), sr)
        print(f"  {out.name}")
    print("\nAudition all four. Tell me the letter that's closest to Reaper.")


if __name__ == "__main__":
    main()
