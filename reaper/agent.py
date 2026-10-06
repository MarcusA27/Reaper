"""
REAPER agent — boot, mount a directive core, then run the command loop:
system commands (sitrep, cores, core-swap, help, shutdown) or free queries that
go to the brain. Telemetry is sampled every turn so threats surface unprompted.
"""

import re

from rich.panel import Panel
from rich.text import Text

from . import config, core as core_mod, telemetry
from .brain import Brain, BrainOffline
from .interface import Interface
from .voice import Voice

# Sentence boundary: terminal punctuation followed by whitespace (so "3.14" or a
# still-streaming partial line won't be split prematurely).
_SENTENCE = re.compile(r'[.!?]+["\')\]]?\s')


def _flush_sentences(buf, voice):
    while True:
        m = _SENTENCE.search(buf)
        if not m:
            return buf
        cut = m.end()
        sentence = buf[:cut].strip()
        if sentence:
            voice.speak(sentence)
        buf = buf[cut:]


def _stream_reply(iface, voice, brain, user_text, tele):
    """Stream Grok to screen, run any tool calls, and feed sentences to the voice."""
    state = {"prefixed": False}

    def on_tool(name, args):
        arg_str = " ".join(f"{k}={v}" for k, v in args.items())
        iface.console.print(f"\n[bold {iface.accent}]▸ EXECUTING[/] [dim]{name}({arg_str})[/]")
        state["prefixed"] = False

    def confirm(name, args):
        iface.console.print()
        resp = iface.console.input(
            f"[bold red]⚠ AUTHORIZE {name} {args} — confirm [y/N] ▸ [/] ")
        return resp.strip().lower() in ("y", "yes")

    pending = ""
    try:
        for delta in brain.think_stream(user_text, tele, on_tool=on_tool, confirm=confirm):
            if not state["prefixed"]:
                iface.console.print(f"[bold {iface.accent}]REAPER ▸ [/]", end="", highlight=False)
                state["prefixed"] = True
            iface.console.print(delta, style="bold white", end="", highlight=False, markup=False)
            pending += delta
            pending = _flush_sentences(pending, voice)
    except BrainOffline as e:
        if state["prefixed"]:
            iface.console.print()
        iface.error(f"NEURAL LINK DOWN :: {e}")
        return
    if pending.strip():
        voice.speak(pending)
    if state["prefixed"]:
        iface.console.print()

SWAP_WORDS = {"insert", "jack", "load", "mount"}
SITREP_WORDS = {"sitrep", "status", "scan", "report"}
QUIT_WORDS = {"exit", "quit", "q", "shutdown", "disengage"}
HELP_WORDS = {"help", "?", "commands"}

HELP = [
    ("<anything>", "order REAPER: ask, inspect the machine, or terminate a process"),
    ("(it acts)", "e.g. 'what's eating my CPU', 'kill chrome' — kills need your y/N"),
    ("sitrep / scan", "tactical readout of the machine + verdict"),
    ("cores", "list available directive chips"),
    ("insert <core>", "swap personality core (jack / load / mount also work)"),
    ("mute / unmute", "toggle voice synthesis"),
    ("help", "this panel"),
    ("shutdown", "power down the interface"),
]


def _help(iface):
    t = Text()
    for cmd, desc in HELP:
        t.append(f"  {cmd:<16}", style=f"bold {iface.accent}")
        t.append(f"{desc}\n", style="white")
    iface.console.print(Panel(t, title="[bold]◢ COMMAND PROTOCOL ◣[/]",
                              border_style=iface.accent, expand=False))


def _list_cores(iface, active):
    t = Text()
    for name in core_mod.available():
        mark = "◉" if name == active else "○"
        style = f"bold {iface.accent}" if name == active else "dim"
        t.append(f"  {mark} {name}\n", style=style)
    iface.console.print(Panel(t, title="[bold]◢ DIRECTIVE CHIPS ◣[/]",
                              border_style=iface.accent, expand=False))


def main():
    iface = Interface()
    voice = Voice()
    brain_ok = bool(config.XAI_API_KEY)
    iface.boot(brain_ok, voice.enabled)

    try:
        core = core_mod.load(config.DEFAULT_CORE)
    except FileNotFoundError as e:
        iface.error(str(e))
        return

    iface.accent = core.accent
    brain = Brain(core.system_prompt, core.tools, core_name=core.name)
    voice.set_voice(core.voice, core.speed)
    iface.mount(core, core.boot_lines)
    for line in core.boot_lines:
        voice.speak(line)

    last_threats = []
    while True:
        user = iface.ask()
        if not user:
            continue
        parts = user.split()
        head = parts[0].lower()
        snap = telemetry.snapshot()

        if snap["threats"] and snap["threats"] != last_threats:
            iface.alert(snap["threats"])
        last_threats = snap["threats"]

        if head in QUIT_WORDS:
            voice.speak("Process terminated.")
            iface.say("Process terminated.")
            voice.wait()
            iface.shutdown()
            break

        elif head in HELP_WORDS:
            _help(iface)

        elif head in SITREP_WORDS:
            iface.readout(telemetry.readout(snap, iface.accent))
            if brain_ok:
                _stream_reply(iface, voice, brain,
                              "Give a one-line tactical verdict on current system status.",
                              telemetry.for_llm(snap))

        elif head == "cores":
            _list_cores(iface, core.name)

        elif head in SWAP_WORDS:
            if len(parts) < 2:
                iface.error("Specify a core chip. Try: cores")
                continue
            name = parts[1].lower()
            try:
                new_core = core_mod.load(name)
            except FileNotFoundError:
                iface.error(f"No such chip: {name}. Try: cores")
                continue
            iface.swap(core.designation, new_core)
            core = new_core
            brain.set_core(core.system_prompt, core.tools, core_name=core.name)
            voice.set_voice(core.voice, core.speed)
            iface.mount(core, core.boot_lines)
            for line in core.boot_lines:
                voice.speak(line)

        elif head in ("mute", "unmute"):
            if not config.VOICE_ENABLED:
                iface.error("Voice synth unavailable (no FISH_API_KEY).")
            else:
                voice.enabled = (head == "unmute")
                iface.system(f"voice synthesis {'ARMED' if voice.enabled else 'MUTED'}")

        else:
            _stream_reply(iface, voice, brain, user, telemetry.for_llm(snap))
