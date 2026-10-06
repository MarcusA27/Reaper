"""
System telemetry — REAPER's sensors.

Gathers a live snapshot of the Operator's machine via psutil, renders it as a
tactical readout for the interface, flattens it for the LLM's context, and trips
threat flags when thresholds are breached.
"""

import time
from collections import deque

import psutil

_HISTORY = deque(maxlen=600)        # ~25 min of samples at the 2.5s push rate
from rich.panel import Panel
from rich.table import Table

from . import config

_BOOT_TIME = psutil.boot_time()
psutil.cpu_percent(interval=None)        # prime: first non-blocking call seeds the delta


def snapshot() -> dict:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    cpu = psutil.cpu_percent(interval=None)   # non-blocking: % since last snapshot
    try:
        load1, load5, load15 = psutil.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = 0.0
    battery = psutil.sensors_battery()
    procs = []
    for p in psutil.process_iter(["name", "cpu_percent"]):
        procs.append((p.info["name"] or "?", p.info["cpu_percent"] or 0.0))
    procs.sort(key=lambda t: -t[1])

    snap = {
        "cpu": cpu,
        "cores": psutil.cpu_count(logical=True),
        "mem_pct": vm.percent,
        "mem_used_gb": vm.used / 1e9,
        "mem_total_gb": vm.total / 1e9,
        "disk_pct": du.percent,
        "disk_free_gb": du.free / 1e9,
        "load": (load1, load5, load15),
        "uptime_s": time.time() - _BOOT_TIME,
        "battery_pct": battery.percent if battery else None,
        "battery_plugged": battery.power_plugged if battery else None,
        "top": procs[:5],
    }
    snap["threats"] = _threats(snap)
    _HISTORY.append((time.time(), snap["cpu"], snap["mem_pct"], snap["disk_pct"]))
    return snap


def trend(minutes=5):
    """Summarize CPU/MEM/DISK movement over the recent history buffer."""
    if len(_HISTORY) < 2:
        return "Insufficient telemetry history yet."
    cutoff = time.time() - minutes * 60
    rows = [r for r in _HISTORY if r[0] >= cutoff]
    if len(rows) < 2:
        return f"Insufficient samples in the last {minutes} min."
    out = [f"Telemetry trend over last {minutes} min ({len(rows)} samples):"]
    for name, i in (("CPU", 1), ("MEM", 2), ("DISK", 3)):
        vals = [r[i] for r in rows]
        avg = sum(vals) / len(vals)
        first, last = vals[0], vals[-1]
        d = "rising" if last - first > 2 else "falling" if first - last > 2 else "stable"
        out.append(f"  {name}: now {last:.0f}%, avg {avg:.0f}%, range {min(vals):.0f}-{max(vals):.0f}%, {d}")
    return "\n".join(out)


def _threats(s: dict) -> list:
    t = []
    if s["cpu"] >= config.ALERT_CPU:
        t.append(f"CPU saturation {s['cpu']:.0f}%")
    if s["mem_pct"] >= config.ALERT_MEM:
        t.append(f"Memory pressure {s['mem_pct']:.0f}%")
    if s["disk_pct"] >= config.ALERT_DISK:
        t.append(f"Disk near capacity {s['disk_pct']:.0f}%")
    if s["battery_pct"] is not None and not s["battery_plugged"] \
            and s["battery_pct"] <= config.ALERT_BATTERY_LOW:
        t.append(f"Battery critical {s['battery_pct']:.0f}%")
    return t


def _bar(pct: float, width: int = 16) -> str:
    fill = int(round(pct / 100 * width))
    return "█" * fill + "░" * (width - fill)


def _fmt_uptime(s: float) -> str:
    d, rem = divmod(int(s), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h:02d}h {m:02d}m"


def readout(s: dict, accent: str = "red") -> Panel:
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="bold")
    t.add_column()

    def line(label, bar, val, crit):
        style = "bold red" if crit else accent
        t.add_row(label, f"[{style}]{bar}[/]  {val}")

    line("CPU", _bar(s["cpu"]), f"{s['cpu']:.0f}%  / {s['cores']} cores", s["cpu"] >= config.ALERT_CPU)
    line("MEM", _bar(s["mem_pct"]), f"{s['mem_used_gb']:.1f}/{s['mem_total_gb']:.0f} GB", s["mem_pct"] >= config.ALERT_MEM)
    line("DISK", _bar(s["disk_pct"]), f"{s['disk_free_gb']:.0f} GB free", s["disk_pct"] >= config.ALERT_DISK)
    if s["battery_pct"] is not None:
        plug = "EXT PWR" if s["battery_plugged"] else "BATTERY"
        crit = (not s["battery_plugged"]) and s["battery_pct"] <= config.ALERT_BATTERY_LOW
        line("PWR", _bar(s["battery_pct"]), f"{s['battery_pct']:.0f}%  {plug}", crit)

    load = "  ".join(f"{x:.2f}" for x in s["load"])
    t.add_row("LOAD", f"[{accent}]{load}[/]")
    t.add_row("UPTIME", f"[{accent}]{_fmt_uptime(s['uptime_s'])}[/]")
    top = "  ".join(f"{n}({c:.0f}%)" for n, c in s["top"][:3] if c > 0) or "idle"
    t.add_row("PROC", f"[dim]{top}[/]")

    title = "[bold]◢ TACTICAL READOUT ◣[/]"
    if s["threats"]:
        title = "[bold red]◢ THREAT DETECTED ◣[/]"
    return Panel(t, title=title, border_style="red" if s["threats"] else accent, expand=False)


def for_llm(s: dict) -> str:
    """Compact telemetry block injected into the agent's context each turn."""
    lines = [
        "LIVE TELEMETRY:",
        f"- CPU: {s['cpu']:.0f}% across {s['cores']} cores; load {s['load'][0]:.2f}",
        f"- Memory: {s['mem_pct']:.0f}% used ({s['mem_used_gb']:.1f}/{s['mem_total_gb']:.0f} GB)",
        f"- Disk(/): {s['disk_pct']:.0f}% used, {s['disk_free_gb']:.0f} GB free",
        f"- Uptime: {_fmt_uptime(s['uptime_s'])}",
    ]
    if s["battery_pct"] is not None:
        lines.append(f"- Power: {s['battery_pct']:.0f}%, {'external' if s['battery_plugged'] else 'on battery'}")
    top = ", ".join(f"{n} {c:.0f}%" for n, c in s["top"][:5] if c > 0) or "none active"
    lines.append(f"- Top processes by CPU: {top}")
    lines.append("THREATS: " + ("; ".join(s["threats"]) if s["threats"] else "none"))
    return "\n".join(lines)
