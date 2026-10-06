"""
Voice output — response text -> Fish Audio TTS -> reaperize chain -> afplay.

Two-stage pipeline to minimize delay: a synth worker renders each line to a WAV
while a separate play worker plays already-rendered lines. So line N+1 is being
synthesized while line N plays, and (driven per-sentence by the agent) the first
sentence starts speaking before the rest of the reply even exists.

Fish runs in "balanced" (low-latency) mode. The active core's voice overrides and
speaking rate are applied per render.
"""

import os
import queue
import subprocess
import tempfile
import threading
import time

import numpy as np
import reaperize                         # repo-root module (run via `python3 -m reaper`)
from fish_audio_sdk import Session, TTSRequest
from fish_audio_sdk.schemas import Prosody

from . import config


def _envelope(y, sr, frame_ms=40):
    """Per-frame RMS amplitude, normalized 0..1 — drives the speaking animation."""
    n = max(1, int(sr * frame_ms / 1000))
    env = [float(np.sqrt(np.mean(y[i:i + n] ** 2))) for i in range(0, len(y), n) if len(y[i:i + n])]
    m = max(env) if env else 1.0
    return [e / (m or 1.0) for e in env], frame_ms / 1000.0


def _trim_silence(x, sr, thresh=0.01, pad_ms=20):
    """Strip leading/trailing silence (Fish pads each clip), then add one short gap."""
    above = np.where(np.abs(x) > thresh * (np.abs(x).max() + 1e-9))[0]
    if len(above) == 0:
        return x
    pad = int(sr * pad_ms / 1000)
    start = max(0, above[0] - pad)
    end = min(len(x), above[-1] + pad)
    gap = np.zeros(int(sr * config.SENTENCE_GAP_MS / 1000))
    return np.concatenate([x[start:end], gap])


class Voice:
    def __init__(self):
        self.enabled = config.VOICE_ENABLED
        self._params = dict(reaperize.PARAMS)
        self._speed = 1.0
        self.on_amp = None                        # callback(level 0..1) during playback
        self.playing = False
        self._session = Session(config.FISH_API_KEY) if self.enabled else None
        self._synth_q: "queue.Queue" = queue.Queue()
        self._play_q: "queue.Queue" = queue.Queue()
        self.last_error = None
        if self.enabled:
            threading.Thread(target=self._synth_worker, daemon=True).start()
            threading.Thread(target=self._play_worker, daemon=True).start()

    def set_voice(self, overrides: dict, speed: float = 1.0):
        self._params = {**reaperize.PARAMS, **(overrides or {})}
        self._speed = speed

    def speak(self, text: str):
        if self.enabled and text.strip():
            self._synth_q.put(text.strip())

    def wait(self):
        """Block until everything queued has finished synthesizing and playing."""
        if self.enabled:
            self._synth_q.join()
            self._play_q.join()

    def busy(self):
        """True while anything is queued to synthesize or actively playing."""
        return self.playing or not self._synth_q.empty() or not self._play_q.empty()

    # ---- stage 1: synthesize ahead of playback ----
    def _synth_worker(self):
        while True:
            text = self._synth_q.get()
            try:
                self._play_q.put(self._render(text))
            except Exception as e:                       # never let voice kill the session
                self.last_error = str(e)
            finally:
                self._synth_q.task_done()

    # ---- stage 2: play rendered files in order, streaming amplitude ----
    def _play_worker(self):
        while True:
            path, env, dt = self._play_q.get()
            try:
                self._play_with_amp(path, env, dt)
            except Exception as e:
                self.last_error = str(e)
            finally:
                if os.path.exists(path):
                    os.remove(path)
                self._play_q.task_done()

    def _play_with_amp(self, path, env, dt):
        self.playing = True
        try:
            proc = subprocess.Popen(["afplay", path])
            start = time.monotonic()
            while proc.poll() is None:
                idx = int((time.monotonic() - start) / dt)
                if self.on_amp:
                    self.on_amp(env[idx] if idx < len(env) else 0.0)
                time.sleep(dt)
        finally:
            self.playing = False
            if self.on_amp:
                self.on_amp(0.0)

    def _render(self, text: str):
        req = TTSRequest(text=text, reference_id=config.FISH_REFERENCE_ID,
                         format="wav", sample_rate=44100, latency="balanced",
                         prosody=Prosody(speed=self._speed))
        raw_fd, raw = tempfile.mkstemp(suffix=".wav")
        out_fd, out = tempfile.mkstemp(suffix=".wav")
        os.close(raw_fd)
        os.close(out_fd)
        with open(raw, "wb") as f:
            for chunk in self._session.tts(req):
                f.write(chunk)
        x, sr = reaperize.read_wav(raw)
        y = _trim_silence(reaperize.reaperize(x, sr, self._params), sr)
        reaperize.write_wav(out, y, sr)
        os.remove(raw)
        env, dt = _envelope(y, sr)
        return out, env, dt
