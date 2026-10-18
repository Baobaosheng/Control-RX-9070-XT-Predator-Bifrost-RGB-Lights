"""Host-animated lighting effects for the BiFrost logo, inspired by the OpenRGB Effects plugin.

Pure computation, no I/O: an effect turns elapsed time into one colour per LED, listed left to
right as the owner sees the logo. `device.BifrostDevice` maps that to the MCU's lamp numbering.
Random effects take a seed so tests are reproducible.
"""

from __future__ import annotations

import colorsys
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

RGB = tuple[int, int, int]

BLACK: RGB = (0, 0, 0)


def parse_color(text: str) -> RGB:
    s = text.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"expected RRGGBB, got {text!r}")
    v = int(s, 16)
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF


def format_color(c: RGB) -> str:
    return f"{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def hsv(h: float, s: float = 1.0, v: float = 1.0) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, max(0.0, min(1.0, v)))
    return round(r * 255), round(g * 255), round(b * 255)


def scale(c: RGB, k: float) -> RGB:
    k = max(0.0, min(1.0, k))
    return round(c[0] * k), round(c[1] * k), round(c[2] * k)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def add(a: RGB, b: RGB) -> RGB:
    return tuple(min(255, x + y) for x, y in zip(a, b))  # type: ignore[return-value]


@dataclass
class Params:
    colors: list[RGB] = field(default_factory=lambda: [(0x00, 0xAE, 0xC7)])
    speed: float = 5.0  # 1 (slow) .. 10 (fast)
    seed: int | None = None

    def color(self, i: int = 0) -> RGB:
        return self.colors[i % len(self.colors)]

    @property
    def rate(self) -> float:
        """Speed mapped to a multiplier: 1 -> 0.33x, 5 -> 1x, 10 -> 4x."""
        s = max(1.0, min(10.0, self.speed))
        return 4.0 ** ((s - 5) / 5)


class Effect:
    """One instance per run. `frame(t)` must be called with non-decreasing t (seconds)."""

    name = ""
    description = ""
    animated = True
    default_colors: Sequence[RGB] = ((0x00, 0xAE, 0xC7),)

    def __init__(self, leds: int, params: Params):
        self.n = leds
        self.p = params
        self.rng = random.Random(params.seed)

    def frame(self, t: float) -> list[RGB]:
        raise NotImplementedError


EFFECTS: dict[str, type[Effect]] = {}


def register(cls: type[Effect]) -> type[Effect]:
    EFFECTS[cls.name] = cls
    return cls


@register
class Static(Effect):
    name, description, animated = "static", "One colour, or one colour per LED if 6 are given", False

    def frame(self, t: float) -> list[RGB]:
        if len(self.p.colors) == self.n:
            return list(self.p.colors)
        return [self.p.color()] * self.n


@register
class Breathing(Effect):
    name, description = "breathing", "Fades in and out; cycles through the given colours"

    def frame(self, t: float) -> list[RGB]:
        period = 4.0 / self.p.rate
        cycle = int(t // period)
        v = 0.5 - 0.5 * math.cos(2 * math.pi * (t % period) / period)
        return [scale(self.p.color(cycle), v)] * self.n


@register
class SpectrumCycle(Effect):
    name, description = "spectrum-cycle", "Whole logo cycles through the colour spectrum"

    def frame(self, t: float) -> list[RGB]:
        return [hsv(t * 0.1 * self.p.rate)] * self.n


@register
class RainbowWave(Effect):
    name, description = "rainbow-wave", "A rainbow travelling across the segments"

    def frame(self, t: float) -> list[RGB]:
        base = t * 0.15 * self.p.rate
        return [hsv(base - i / self.n) for i in range(self.n)]


@register
class GradientWave(Effect):
    name, description = "gradient-wave", "Two colours flowing into each other across the logo"
    default_colors = ((0xFF, 0x00, 0x80), (0x00, 0x80, 0xFF))

    def frame(self, t: float) -> list[RGB]:
        a, b = self.p.color(0), self.p.color(1)
        phase = t * 0.5 * self.p.rate
        return [mix(a, b, 0.5 - 0.5 * math.cos(2 * math.pi * (phase - i / self.n))) for i in range(self.n)]


@register
class Comet(Effect):
    name, description = "comet", "A bright head with a fading tail, bouncing across the logo"

    def frame(self, t: float) -> list[RGB]:
        span = 2 * (self.n - 1) + 4  # travel past the edges so the tail clears
        pos = (t * 4.0 * self.p.rate) % span - 2
        out = []
        for i in range(self.n):
            d = pos - i
            out.append(scale(self.p.color(), max(0.0, 1.0 - d / 3.0)) if 0 <= d <= 3 else BLACK)
        return out


@register
class Visor(Effect):
    name, description = "visor", "A scanner sweeping left and right"

    def frame(self, t: float) -> list[RGB]:
        x = (math.sin(t * 1.5 * self.p.rate) + 1) / 2 * (self.n - 1)
        return [scale(self.p.color(), max(0.0, 1.0 - abs(i - x))) for i in range(self.n)]


@register
class Marquee(Effect):
    name, description = "marquee", "Alternating lit segments marching sideways"
    default_colors = ((0xFF, 0x30, 0x00), (0x00, 0x00, 0x00))

    def frame(self, t: float) -> list[RGB]:
        step = int(t * 4.0 * self.p.rate)
        return [self.p.color(0) if (i + step) % 3 == 0 else self.p.color(1) for i in range(self.n)]


@register
class Fill(Effect):
    name, description = "fill", "Segments light up one by one, then the next colour fills in"
    default_colors = ((0xFF, 0x00, 0x00), (0x00, 0xFF, 0x00), (0x00, 0x00, 0xFF))

    def frame(self, t: float) -> list[RGB]:
        steps = int(t * 3.0 * self.p.rate)
        round_, filled = divmod(steps, self.n)
        new, old = self.p.color(round_ + 1), self.p.color(round_)
        return [new if i <= filled else old for i in range(self.n)]


@register
class SmoothBlink(Effect):
    name, description = "smooth-blink", "Short soft pulses with pauses"

    def frame(self, t: float) -> list[RGB]:
        period = 2.0 / self.p.rate
        x = (t % period) / period
        v = math.sin(math.pi * x / 0.4) if x < 0.4 else 0.0
        return [scale(self.p.color(int(t // period)), v)] * self.n


@register
class StarryNight(Effect):
    name, description = "starry-night", "Random segments twinkle and fade"

    def __init__(self, leds: int, params: Params):
        super().__init__(leds, params)
        self.level = [0.0] * leds
        self.hue = [self.p.color(i) for i in range(leds)]
        self.last = 0.0

    def frame(self, t: float) -> list[RGB]:
        dt, self.last = max(0.0, t - self.last), t
        for i in range(self.n):
            self.level[i] = max(0.0, self.level[i] - dt * 0.8 * self.p.rate)
            if self.rng.random() < dt * 0.6 * self.p.rate:
                self.level[i] = 1.0
                self.hue[i] = self.p.color(self.rng.randrange(len(self.p.colors)))
        return [scale(c, v) for c, v in zip(self.hue, self.level)]


@register
class Lightning(Effect):
    name, description = "lightning", "Dark sky with random flashes"
    default_colors = ((0xB0, 0xC0, 0xFF),)

    def __init__(self, leds: int, params: Params):
        super().__init__(leds, params)
        self.flash = 0.0
        self.last = 0.0

    def frame(self, t: float) -> list[RGB]:
        dt, self.last = max(0.0, t - self.last), t
        self.flash = max(0.0, self.flash - dt * 4.0)
        if self.rng.random() < dt * 0.4 * self.p.rate:
            self.flash = 1.0
        return [scale(self.p.color(), self.flash)] * self.n


@register
class Swap(Effect):
    name, description = "swap", "Two colours swapping sides of the logo"
    default_colors = ((0xFF, 0x00, 0x00), (0x00, 0x00, 0xFF))

    def frame(self, t: float) -> list[RGB]:
        a, b = self.p.color(0), self.p.color(1)
        k = 0.5 - 0.5 * math.cos(math.pi * t * 0.5 * self.p.rate)
        half = self.n // 2
        return [mix(a, b, k)] * half + [mix(b, a, k)] * (self.n - half)


def make(name: str, leds: int, params: Params) -> Effect:
    try:
        cls = EFFECTS[name]
    except KeyError:
        raise ValueError(f"unknown effect {name!r}; choose from {', '.join(EFFECTS)}") from None
    return cls(leds, params)


def apply_brightness(colors: Sequence[RGB], percent: float) -> list[RGB]:
    k = max(0.0, min(100.0, percent)) / 100.0
    return [scale(c, k) for c in colors]


Renderer = Callable[[float], list[RGB]]
