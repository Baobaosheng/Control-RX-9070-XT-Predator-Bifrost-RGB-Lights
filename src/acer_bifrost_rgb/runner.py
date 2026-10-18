"""Drive a `BifrostDevice` from an effect at a fixed frame rate."""

from __future__ import annotations

import signal
import time
from collections.abc import Callable

from . import effects
from .device import BifrostDevice

MAX_FPS = 30
DEFAULT_FPS = 25
MAX_CONSECUTIVE_ERRORS = 5


class Stop(Exception):
    pass


def _raise_stop(*_args: object) -> None:
    raise Stop


def run(
    dev: BifrostDevice,
    effect: effects.Effect,
    brightness: float = 100.0,
    fps: float = DEFAULT_FPS,
    duration: float | None = None,
    log: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Animate until `duration` elapses, SIGINT/SIGTERM, or repeated I/O errors. Returns an exit code."""
    fps = max(1.0, min(float(MAX_FPS), fps))
    period = 1.0 / fps
    previous = signal.signal(signal.SIGTERM, _raise_stop)
    start, frames, errors = clock(), 0, 0
    try:
        while True:
            now = clock() - start
            if duration is not None and now >= duration:
                return 0
            colors = effects.apply_brightness(effect.frame(now), brightness)
            try:
                dev.show(colors)
                errors = 0
            except OSError as e:
                errors += 1
                log(f"I/O error {errors}/{MAX_CONSECUTIVE_ERRORS}: {e.strerror or e}")
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    return 1
                sleep(1.0)
            frames += 1
            if not effect.animated:
                return 0
            sleep(max(0.0, start + frames * period - clock()))
    except (KeyboardInterrupt, Stop):
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)
