# REAPER

A dark-machine ops watchdog with a voice. You type orders; it answers in a
synthesized robot voice inside a military terminal. Its personality lives on
swappable **directive cores** — load one and it reboots as a different machine
with different directives, a different voice, and a different interface.

## Pieces

| File | Role |
|---|---|
| `generate_reaper_clips.py` | TTS the canned voice lines from Fish Audio |
| `reaperize.py` | the voice effect chain (vocoder + comms + grit + formant) |
| `analyze_voice.py` | spectral analysis used to tune the voice |
| `reaper/` | the agent (interface, brain, telemetry, voice, cores) |
| `cores/*.toml` | personality cores — the "USB directive chips" |

## Run

```bash
export XAI_API_KEY="..."     # the brain (xAI / Grok)
export FISH_API_KEY="..."    # the voice (Fish Audio)
python3 -m reaper
```

Without `XAI_API_KEY` the interface still boots but the brain is offline.
Without `FISH_API_KEY` (or with `REAPER_MUTE=1`) it runs silent — text only.

## Commands

- `sitrep` / `scan` — tactical readout of the machine + a spoken verdict
- `cores` — list available directive chips
- `insert <core>` — swap personality core (`jack` / `load` / `mount` also work)
- `mute` / `unmute` — toggle voice
- `help` — command protocol
- `shutdown` — power down
- anything else — an order/query for the active core

## Actions (tool-use)

REAPER can inspect and act on the machine through natural orders — it decides when
to use its tools:

- inspect: processes (list/find/detail), disk usage, network bandwidth +
  connections, recent system error logs, recent file changes, and a CPU/mem/disk
  trend buffer for extrapolation (`what's hogging memory?`, `what's it talking to?`,
  `any errors lately?`, `where's memory trending?`)
- act: terminate a process (`kill chrome`)

Terminating a process is gated: the interface prompts `⚠ AUTHORIZE kill_process …
[y/N]` before anything dies, and protected system processes (launchd, WindowServer,
etc.) are always refused.

## Writing a core

Drop a `cores/<name>.toml` file:

```toml
designation = "WARDEN // SEC-7"
signature   = "..."
accent      = "green"                 # rich color for the interface
speed       = 0.9                     # TTS speaking rate (1.0 normal, lower = slower)
boot_lines  = ["Warden online."]      # spoken on mount
system_prompt = """..."""             # the personality / directives

[voice]                               # optional reaperize PARAMS overrides
drive = 5.0
formant_ratio = 0.8
```

Keep top-level keys above the `[voice]` table (TOML rule). Then `insert warden`.

## Config (env)

- `REAPER_MODEL` — xAI model (default `grok-4.3`)
- `REAPER_VOICE_ID` — Fish reference id (default = the tuned Reaper voice)
- `REAPER_CORE` — core to boot into (default `reaper`)
- `REAPER_MUTE=1` — boot silent
