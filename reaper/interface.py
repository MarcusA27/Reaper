"""
The combat interface — military TUI built on Rich.

Boot sequence, phosphor styling, char-by-char "typing" for spoken lines, threat
banners, the tactical readout, and the core-swap "USB flash" reboot animation.
"""

import time

from rich.align import Align
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

BANNER = r"""
 ▄▄▄  ▓█████ ▄▄▄       ██▓███  ▓█████  ██▀███
▒████▄ ▓█   ▀▒████▄    ▓██░  ██▒▓█   ▀ ▓██ ▒ ██▒
▒██  ▀█▄▒███  ▒██  ▀█▄  ▓██░ ██▓▒▒███   ▓██ ░▄█ ▒
░██▄▄▄▄██▒▓█  ▄░██▄▄▄▄██ ▒██▄█▓▒ ▒▒▓█  ▄ ▒██▀▀█▄
 ▓█   ▓██░▒████▒▓█   ▓██▒▒██▒ ░  ░░▒████▒░██▓ ▒██▒
"""


class Interface:
    def __init__(self, accent: str = "red"):
        self.console = Console()
        self.accent = accent

    # ---- low-level styled output ----
    def _line(self, text, style=None, delay=0.0):
        self.console.print(text, style=style, highlight=False)
        if delay:
            time.sleep(delay)

    def system(self, text):
        self._line(f"[dim]· {text}[/]")

    def typed(self, prefix, text, style, delay=0.012):
        self.console.print(prefix, style=f"bold {self.accent}", end="", highlight=False)
        for ch in text:
            self.console.print(ch, style=style, end="", highlight=False, markup=False)
            time.sleep(delay)
        self.console.print()

    # ---- boot ----
    def boot(self, brain_ok: bool, voice_ok: bool):
        self.console.clear()
        self.console.print(Align.center(Text(BANNER, style=f"bold {self.accent}")))
        self.console.print(Align.center(
            Text("E W R - 1 1 5   //   C O M B A T   I N T E R F A C E", style="bold white on red")))
        self.console.print()
        checks = [
            ("POWER-ON SELF TEST", "OK", "green"),
            ("SENSOR ARRAY", "ONLINE", "green"),
            ("TELEMETRY UPLINK", "LOCKED", "green"),
            ("NEURAL LINK  [xAI/GROK]", "ONLINE" if brain_ok else "NO KEY", "green" if brain_ok else "yellow"),
            ("VOICE SYNTH  [FISH]", "ARMED" if voice_ok else "MUTED", "green" if voice_ok else "yellow"),
            ("DIRECTIVE CORE SLOT", "READY", "green"),
        ]
        for label, status, color in checks:
            dots = "." * max(2, 34 - len(label))
            self.console.print(f"  [dim]{escape(label)}[/] [dim]{dots}[/] [{color}]{status}[/]")
            time.sleep(0.18)
        self.console.print()

    def mount(self, core, spoken):
        self.console.print(Panel(
            Text(f"{core.designation}\n{core.signature}", justify="center", style="bold"),
            title="[bold]◢ DIRECTIVE CORE MOUNTED ◣[/]", border_style=core.accent, expand=False))
        for line in spoken:
            self.typed("REAPER ▸ ", line, style="bold white")

    # ---- core swap: the "USB into its head" moment ----
    def swap(self, old_designation, new_core):
        seq = [
            (f"⚠  CORE EXTRACTION INITIATED", "bold yellow", 0.3),
            (f"   DECOUPLING DIRECTIVE LAYER :: {old_designation}", "yellow", 0.25),
            (f"   PURGING ACTIVE DIRECTIVES ████████████  WIPED", "red", 0.3),
            (f"   NEW CHIP DETECTED :: {new_core.designation}", f"bold {new_core.accent}", 0.35),
        ]
        for text, style, pause in seq:
            self._line(text, style=style)
            time.sleep(pause)
        # flash progress
        self.console.print("   FLASHING CORE  ", end="", highlight=False)
        for _ in range(24):
            self.console.print("▓", style=new_core.accent, end="", highlight=False)
            time.sleep(0.04)
        self.console.print("  100%")
        time.sleep(0.2)
        self._line("   REBOOTING DIRECTIVE LAYER...", style="bold", delay=0.6)
        self.accent = new_core.accent
        self.console.print()

    # ---- readout / alerts ----
    def readout(self, panel):
        self.console.print(panel)

    def alert(self, threats):
        if not threats:
            return
        body = "\n".join(f"  ‼ {t}" for t in threats)
        self.console.print(Panel(Text(body, style="bold red"),
                                 title="[blink bold red]◢ THREAT ◣[/]", border_style="red", expand=False))

    # ---- io ----
    def ask(self) -> str:
        try:
            return self.console.input(f"\n[bold {self.accent}]OPERATOR ▸ [/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return "shutdown"

    def say(self, text):
        self.typed("REAPER ▸ ", text, style="bold white")

    def error(self, text):
        self._line(f"[bold red]✖ {text}[/]")

    def shutdown(self):
        self._line("\n[bold red]DIRECTIVE COMPLETE. THIS UNIT POWERING DOWN.[/]", delay=0.4)
        self._line("[dim]· link severed ·[/]")
