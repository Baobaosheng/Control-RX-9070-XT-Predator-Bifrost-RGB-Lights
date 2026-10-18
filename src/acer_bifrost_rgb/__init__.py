"""Linux control for Acer Predator BiFrost GPU RGB lighting."""

from __future__ import annotations

import sys

from .bifrost_cli import main as _main

__all__ = ["main"]


def main() -> None:
    sys.exit(_main())
