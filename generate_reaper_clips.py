"""
generate_reaper_clips.py

Pulls each Reaper line as its own WAV from the Fish Audio "Reaper base" voice.
Solo generation, one line per file — the honest test and the production condition.
Output is 44.1kHz / 16-bit / mono WAV, ready to drop into your DSP chain.

Setup:
    pip3 install fish-audio-sdk
    export FISH_API_KEY="sk-..."        # don't hardcode the key
    # paste your "Reaper base" model id into REFERENCE_ID below

Run:
    python3 generate_reaper_clips.py --test   # one clip, to audition the voice
    python3 generate_reaper_clips.py          # the full batch
"""

import argparse
import os
from pathlib import Path
from fish_audio_sdk import Session, TTSRequest

API_KEY = os.environ["FISH_API_KEY"]          # read from env, not the source
REFERENCE_ID = "92cd722f70ce4319809889e68bff4781"  # the model id from the designer

OUT_DIR = Path("reaper_clips")
SAMPLE_RATE = 44100                            # wav comes out 16-bit mono
# Leave backend at the SDK default; pin a model only if a line sounds off,
# e.g. session.tts(req, backend="s1") or backend="speech-1.5".

# The voice bible, as data. Add lines freely — filenames follow the moment key.
LINES = {
    "boot": [
        "Systems online.",
        "Resumed. Last session ended mid-refactor. Continue.",
    ],
    "ack": [
        "Acknowledged.",
        "Directive received. Beginning.",
    ],
    "work": [
        "Accessing.",
        "Scanning your repository. Stand by.",
        "Four files match. Opening the first.",
    ],
    "result": [
        "Line 88. Your null check is missing.",
        "The leak is in your view controller. It does not deallocate.",
    ],
    "success": [
        "Compiled. Zero warnings.",
        "Process terminated.",
    ],
    "fail": [
        "Build failed. Forty-one errors. Beginning triage.",
        "Tests failing. Three. I traced the cause. You will not like it.",
        "Warning. Your last commit broke main.",
    ],
    "refuse": [
        "Negative.",
        "Negative. That command drops your database. Confirm if you meant it.",
    ],
    "opinion": [
        "Your architecture is wrong. Stating this once.",
        "You asked for three abstraction layers. You need one. "
        "Proceeding with one unless you object.",
    ],
    "interrupt": [
        "Stop. You are describing the symptom. The cause is your cache.",
        "Pause. This is last Tuesday's mistake. Again.",
    ],
    "idle": [
        "You have stared at line 200 for six minutes. The bug is on line 47.",
        "Your build has been red for an hour. Acknowledge, or I fix it.",
    ],
}


def generate(session, moment, i, text):
    out = OUT_DIR / f"{moment}_{i:02d}.wav"
    req = TTSRequest(
        text=text,
        reference_id=REFERENCE_ID,
        format="wav",
        sample_rate=SAMPLE_RATE,
        latency="normal",        # quality mode; you're not realtime yet
    )
    with open(out, "wb") as f:
        for chunk in session.tts(req):
            f.write(chunk)
    print(f"  {out}  <-  {text!r}")


def main():
    if REFERENCE_ID.startswith("PASTE_"):
        raise SystemExit("Set REFERENCE_ID to your 'Reaper base' model id first.")

    parser = argparse.ArgumentParser(description="Generate Reaper voice clips via Fish Audio.")
    parser.add_argument(
        "--test", action="store_true",
        help="Generate a single clip (boot_01) to audition the voice before the full batch.",
    )
    args = parser.parse_args()

    session = Session(API_KEY)
    OUT_DIR.mkdir(exist_ok=True)

    if args.test:
        moment = "boot"
        generate(session, moment, 1, LINES[moment][0])
        print(f"\nTest clip in {OUT_DIR}/. Sounds right? Run without --test for all clips.")
        return

    for moment, lines in LINES.items():
        for i, text in enumerate(lines, start=1):
            generate(session, moment, i, text)

    total = sum(len(v) for v in LINES.values())
    print(f"\nDone. {total} clips in {OUT_DIR}/")


if __name__ == "__main__":
    main()
