"""The saved lighting setting, re-applied at boot (`acer-bifrost-rgb apply`)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import effects


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "acer-bifrost-rgb" / "config.toml"


@dataclass
class Setting:
    effect: str = "static"
    colors: list[str] = field(default_factory=lambda: ["00aec7"])
    speed: float = 5.0
    brightness: float = 100.0
    fps: float = 25.0

    def params(self) -> effects.Params:
        return effects.Params(
            colors=[effects.parse_color(c) for c in self.colors],
            speed=self.speed,
        )

    def dumps(self) -> str:
        colors = ", ".join(f'"{c}"' for c in self.colors)
        return (
            "# acer-bifrost-rgb saved setting — written by `acer-bifrost-rgb … --save`\n"
            f'effect = "{self.effect}"\n'
            f"colors = [{colors}]\n"
            f"speed = {self.speed:g}\n"
            f"brightness = {self.brightness:g}\n"
            f"fps = {self.fps:g}\n"
        )


def load(p: Path | None = None) -> Setting:
    p = p or path()
    data = tomllib.loads(p.read_text())
    s = Setting(**{k: data[k] for k in Setting.__dataclass_fields__ if k in data})
    effects.make(s.effect, 6, s.params())  # validate name and colours early
    return s


def save(s: Setting, p: Path | None = None) -> Path:
    p = p or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(s.dumps())
    tmp.replace(p)
    return p
