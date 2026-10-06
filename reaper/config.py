"""Environment, paths, and constants for the REAPER agent."""

import os
from pathlib import Path

# --- brain (xAI / Grok) ---
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_URL = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = os.environ.get("REAPER_MODEL", "grok-4.3")   # verified current model, June 2026

# --- voice (Fish Audio -> reaperize) ---
FISH_API_KEY = os.environ.get("FISH_API_KEY", "")
FISH_REFERENCE_ID = os.environ.get("REAPER_VOICE_ID", "92cd722f70ce4319809889e68bff4781")
VOICE_ENABLED = bool(FISH_API_KEY) and os.environ.get("REAPER_MUTE", "") != "1"

# --- web search (Brave Search API) ---
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

# --- paths ---
ROOT = Path(__file__).resolve().parent.parent
CORES_DIR = ROOT / "cores"
MEMORY_DIR = ROOT / "memory"
TASKS_DIR = ROOT / "tasks"
DEFAULT_CORE = os.environ.get("REAPER_CORE", "reaper")

# --- speech pacing ---
# Silence is trimmed off each synthesized sentence, then this gap is added between
# them. Lower = snappier delivery. Tune via REAPER_GAP_MS.
SENTENCE_GAP_MS = int(os.environ.get("REAPER_GAP_MS", "70"))

# --- watchdog thresholds (percent) that trip a threat flag ---
ALERT_CPU = 90
ALERT_MEM = 90
ALERT_DISK = 90
ALERT_BATTERY_LOW = 15
