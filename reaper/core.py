"""
Personality cores — the swappable "directive chips".

Each core is a cores/<name>.toml file holding the agent's system prompt, its
own voice tuning (reaperize overrides), boot lines, and interface accent. Loading
one is the "plug a USB into its head" moment: new directives, new voice, reboot.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import tomllib                       # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib              # 3.9/3.10 backport

from . import config


@dataclass
class Core:
    name: str                            # file stem, e.g. "reaper"
    designation: str                     # display callsign, e.g. "REAPER // EWR-115"
    system_prompt: str                   # the core directives (personality)
    boot_lines: list = field(default_factory=list)   # spoken on mount
    signature: str = ""                  # one-line motto shown under the banner
    accent: str = "red"                  # rich color for the interface
    speed: float = 1.0                   # TTS speaking rate (1.0 normal, <1 slower)
    tools: Optional[list] = None         # capability scope: group/tool names; None = all, [] = none
    voice: dict = field(default_factory=dict)         # reaperize PARAMS overrides


def _path(name: str) -> Path:
    return config.CORES_DIR / f"{name}.toml"


def available() -> list:
    if not config.CORES_DIR.exists():
        return []
    return sorted(p.stem for p in config.CORES_DIR.glob("*.toml"))


def load(name: str) -> Core:
    path = _path(name)
    if not path.exists():
        raise FileNotFoundError(f"No core chip '{name}' in {config.CORES_DIR}")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Core(
        name=name,
        designation=data.get("designation", name.upper()),
        system_prompt=data["system_prompt"].strip(),
        boot_lines=data.get("boot_lines", []),
        signature=data.get("signature", ""),
        accent=data.get("accent", "red"),
        speed=float(data.get("speed", 1.0)),
        tools=data.get("tools"),
        voice=data.get("voice", {}),
    )
