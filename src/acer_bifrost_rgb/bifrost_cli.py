"""`acer-bifrost-rgb`: colours and effects for the Predator BiFrost RX 9070 XT logo on Linux.

Talks to the logo's lighting MCU (docs/REGISTERS.md). Writes go to the hardware unless
`--dry-run` is given; colours are listed left to right as seen on the card.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import bus, config, effects, ite, runner
from .device import BifrostDevice, DeviceError

SERVICE_NAME = "acer-bifrost-rgb.service"


def _color(text: str) -> str:
    try:
        return effects.format_color(effects.parse_color(text))
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _percent(text: str) -> float:
    v = float(text)
    if not 0 <= v <= 100:
        raise argparse.ArgumentTypeError("brightness must be 0..100")
    return v


def _speed(text: str) -> float:
    v = float(text)
    if not 1 <= v <= 10:
        raise argparse.ArgumentTypeError("speed must be 1..10")
    return v


def _fps(text: str) -> float:
    v = float(text)
    if not 1 <= v <= runner.MAX_FPS:
        raise argparse.ArgumentTypeError(f"fps must be 1..{runner.MAX_FPS}")
    return v


def _setting_from_args(args: argparse.Namespace) -> config.Setting:
    if args.cmd == "color":
        return config.Setting("static", [args.color], brightness=args.brightness)
    if args.cmd == "lamps":
        return config.Setting("static", list(args.colors), brightness=args.brightness)
    if args.cmd == "off":
        return config.Setting("static", ["000000"])
    cls = effects.EFFECTS[args.name]
    colors = args.colors or [effects.format_color(c) for c in cls.default_colors]
    return config.Setting(args.name, colors, args.speed, args.brightness, args.fps)


def _play(args: argparse.Namespace, setting: config.Setting, duration: float | None = None) -> int:
    log = print if args.verbose or args.dry_run else (lambda _m: None)
    try:
        with BifrostDevice(args.bus, dry_run=args.dry_run, log=log) as dev:
            effect = effects.make(setting.effect, dev.lamps, setting.params())
            if args.dry_run and effect.animated and duration is None:
                duration = 1.0  # show one second of frames, not forever
            code = runner.run(dev, effect, setting.brightness, setting.fps, duration, log=print)
            if args.dry_run:
                print(f"(dry run: {dev.writes} write(s) not sent)")
            return code
    except (DeviceError, RuntimeError, PermissionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_show(args: argparse.Namespace) -> int:
    setting = _setting_from_args(args)
    if args.save:
        print(f"saved to {config.save(setting)}")
    return _play(args, setting, getattr(args, "duration", None))


def cmd_apply(args: argparse.Namespace) -> int:
    p = Path(args.config) if args.config else config.path()
    try:
        setting = config.load(p)
    except FileNotFoundError:
        print(f"error: no saved setting at {p}; use a command with --save first", file=sys.stderr)
        return 1
    return _play(args, setting)


def cmd_release(args: argparse.Namespace) -> int:
    log = print if args.verbose or args.dry_run else (lambda _m: None)
    try:
        with BifrostDevice(args.bus, dry_run=args.dry_run, log=log) as dev:
            dev.release()
    except (DeviceError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("lamps handed back to the MCU's built-in effect (dark on this card)")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    try:
        adapter = bus.find_oem_bus() if args.bus is None else None
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    number = args.bus if args.bus is not None else adapter.number
    print(f"bus:     i2c-{number}" + (f" ({adapter.name}, {adapter.pci})" if adapter else ""))
    print(f"address: 0x{ite.I2C_ADDRESS:02x} (lighting MCU)")
    if args.dry_run:
        return 0
    try:
        with BifrostDevice(number) as dev:
            print(f"lamps:   {dev.read_lamp_count()} (logo segments, listed left to right)")
    except (DeviceError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"saved:   {config.path()}" + ("" if config.path().exists() else " (none yet)"))
    return 0


def cmd_effects(_args: argparse.Namespace) -> int:
    width = max(len(n) for n in effects.EFFECTS)
    for name, cls in effects.EFFECTS.items():
        defaults = " ".join(effects.format_color(c) for c in cls.default_colors)
        print(f"  {name:<{width}}  {cls.description}  [default colours: {defaults}]")
    return 0


def service_unit() -> str:
    uv = shutil.which("uv") or "uv"
    project = Path(__file__).resolve().parents[2]
    return (
        "[Unit]\n"
        "Description=Acer Predator BiFrost logo lighting (re-applies the saved setting)\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={uv} run --project {project} acer-bifrost-rgb apply\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def cmd_service(args: argparse.Namespace) -> int:
    unit = service_unit()
    if not args.write:
        print(unit, end="")
        return 0
    dest = Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(unit)
    print(f"wrote {dest}\nenable it with:\n  systemctl --user daemon-reload\n"
          f"  systemctl --user enable --now {SERVICE_NAME}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bus", type=int, default=argparse.SUPPRESS, help="override OEM bus autodetection")
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="print the register writes instead of sending them")
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
                        help="print every register write")

    show = argparse.ArgumentParser(add_help=False)
    show.add_argument("--brightness", type=_percent, default=100.0, help="0..100 (default 100)")
    show.add_argument("--save", action="store_true", help="also save as the setting `apply` restores")

    ap = argparse.ArgumentParser(prog="acer-bifrost-rgb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", parents=[common], help="bus, address, lamp count").set_defaults(fn=cmd_info)
    sub.add_parser("effects", parents=[common], help="list effects").set_defaults(fn=cmd_effects)

    p = sub.add_parser("color", parents=[common, show], help="whole logo one colour")
    p.add_argument("color", type=_color, help="RRGGBB")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("lamps", parents=[common, show], help="one colour per segment, left to right")
    p.add_argument("colors", type=_color, nargs=ite.MAX_LAMPS, metavar="RRGGBB")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("effect", parents=[common, show], help="run an animated effect (Ctrl+C to stop)")
    p.add_argument("name", choices=list(effects.EFFECTS))
    p.add_argument("--colors", type=_color, nargs="+", metavar="RRGGBB", help="effect colours")
    p.add_argument("--speed", type=_speed, default=5.0, help="1..10 (default 5)")
    p.add_argument("--fps", type=_fps, default=runner.DEFAULT_FPS, help=f"frame rate, max {runner.MAX_FPS}")
    p.add_argument("--duration", type=float, help="stop after N seconds")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("off", parents=[common], help="all segments black (stays under host control)")
    p.add_argument("--save", action="store_true", help="also save as the setting `apply` restores")
    p.set_defaults(fn=cmd_show, brightness=100.0)

    p = sub.add_parser("release", parents=[common], help="hand the lamps back to the MCU (0x06 = 1)")
    p.set_defaults(fn=cmd_release)

    p = sub.add_parser("apply", parents=[common], help="re-apply the saved setting (used at boot)")
    p.add_argument("--config", help=f"setting file (default {config.path()})")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("service", parents=[common], help="print or install the systemd user unit")
    p.add_argument("--write", action="store_true", help=f"write ~/.config/systemd/user/{SERVICE_NAME}")
    p.set_defaults(fn=cmd_service)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for name, default in (("bus", None), ("dry_run", False), ("verbose", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    return args.fn(args)
