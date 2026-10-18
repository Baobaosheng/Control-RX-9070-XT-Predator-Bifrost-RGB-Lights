"""Tests for the effects library, the device layer, the runner and the saved setting. No hardware."""

from __future__ import annotations

import pytest

from acer_bifrost_rgb import bifrost_cli, config, effects, runner
from acer_bifrost_rgb.device import BifrostDevice

LEDS = 6


def make_device() -> tuple[BifrostDevice, list[str]]:
    writes: list[str] = []
    dev = BifrostDevice(bus_number=99, dry_run=True, log=writes.append)
    return dev, writes


# --- effects ---------------------------------------------------------------------


@pytest.mark.parametrize("name", list(effects.EFFECTS))
@pytest.mark.parametrize("t", [0.0, 0.37, 1.0, 5.5, 60.0])
def test_every_effect_returns_valid_frames(name, t):
    eff = effects.make(name, LEDS, effects.Params(colors=list(effects.EFFECTS[name].default_colors), seed=1))
    frame = eff.frame(t)
    assert len(frame) == LEDS
    assert all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in frame)


@pytest.mark.parametrize("name", ["starry-night", "lightning"])
def test_random_effects_are_reproducible_with_a_seed(name):
    def run():
        eff = effects.make(name, LEDS, effects.Params(seed=42))
        return [eff.frame(i / 25) for i in range(200)]

    assert run() == run()


def test_static_single_and_per_led():
    assert effects.make("static", LEDS, effects.Params(colors=[(1, 2, 3)])).frame(0) == [(1, 2, 3)] * LEDS
    six = [(i, i, i) for i in range(LEDS)]
    assert effects.make("static", LEDS, effects.Params(colors=six)).frame(9) == six


def test_breathing_goes_dark_and_bright():
    eff = effects.make("breathing", LEDS, effects.Params(colors=[(200, 100, 0)]))
    assert eff.frame(0.0)[0] == (0, 0, 0)
    assert eff.frame(2.0)[0] == (200, 100, 0)  # half of the 4 s period at speed 5


def test_rainbow_wave_differs_across_segments():
    frame = effects.make("rainbow-wave", LEDS, effects.Params()).frame(0.0)
    assert len(set(frame)) == LEDS


def test_speed_mapping_monotonic_and_centred():
    rates = [effects.Params(speed=s).rate for s in range(1, 11)]
    assert rates == sorted(rates)
    assert effects.Params(speed=5).rate == pytest.approx(1.0)
    assert effects.Params(speed=10).rate == pytest.approx(4.0)


def test_unknown_effect_rejected():
    with pytest.raises(ValueError):
        effects.make("disco", LEDS, effects.Params())


def test_brightness_scales():
    assert effects.apply_brightness([(200, 100, 50)], 50) == [(100, 50, 25)]
    assert effects.apply_brightness([(200, 100, 50)], 0) == [(0, 0, 0)]


def test_color_parsing():
    assert effects.parse_color("#00AeC7") == (0x00, 0xAE, 0xC7)
    with pytest.raises(ValueError):
        effects.parse_color("fff")


# --- device ----------------------------------------------------------------------


def test_uniform_frame_is_one_range_write_after_host_control():
    dev, writes = make_device()
    dev.fill((255, 0, 0))
    assert writes == ["W 06 00", "W 05 01 00 00 05 00 ff 00 00 ff"]


def test_per_led_frame_matches_hardware_lamp_order():
    # On the card, lamps 0..5 = red, green, blue, yellow, cyan, magenta show as
    # magenta, cyan, yellow, blue, green, red from left to right.
    dev, writes = make_device()
    left_to_right = [(255, 0, 255), (0, 255, 255), (255, 255, 0), (0, 0, 255), (0, 255, 0), (255, 0, 0)]
    dev.show(left_to_right)
    assert writes == [
        "W 06 00",
        "W 04 00 00 ff 00 00 ff 01 00 ff 00 ff",
        "W 04 00 02 00 00 ff ff 03 ff ff 00 ff",
        "W 04 01 04 00 ff ff ff 05 ff 00 ff ff",
    ]


def test_unchanged_frame_is_skipped_and_host_control_sent_once():
    dev, writes = make_device()
    assert dev.fill((1, 2, 3))
    assert not dev.fill((1, 2, 3))
    assert dev.fill((3, 2, 1))
    assert writes.count("W 06 00") == 1
    assert len(writes) == 3


def test_release_then_show_retakes_control():
    dev, writes = make_device()
    dev.fill((9, 9, 9))
    dev.release()
    dev.fill((9, 9, 9))
    assert writes == ["W 06 00", "W 05 01 00 00 05 00 09 09 09 ff", "W 06 01", "W 06 00",
                      "W 05 01 00 00 05 00 09 09 09 ff"]


def test_wrong_led_count_rejected():
    dev, _ = make_device()
    with pytest.raises(ValueError):
        dev.show([(0, 0, 0)] * 5)


# --- runner ----------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += max(s, 1e-6)


def test_static_effect_writes_once_and_returns():
    dev, writes = make_device()
    clock = FakeClock()
    eff = effects.make("static", LEDS, effects.Params(colors=[(5, 5, 5)]))
    assert runner.run(dev, eff, clock=clock, sleep=clock.sleep, log=lambda _m: None) == 0
    assert writes == ["W 06 00", "W 05 01 00 00 05 00 05 05 05 ff"]


def test_animated_effect_respects_fps_and_duration():
    dev, _ = make_device()
    clock = FakeClock()
    shown = []
    orig = dev.show
    dev.show = lambda colors, force=False: shown.append(colors) or orig(colors, force)  # type: ignore[method-assign]
    eff = effects.make("spectrum-cycle", LEDS, effects.Params())
    runner.run(dev, eff, fps=20, duration=2.0, clock=clock, sleep=clock.sleep, log=lambda _m: None)
    assert 39 <= len(shown) <= 41


def test_fps_is_capped():
    dev, _ = make_device()
    clock = FakeClock()
    count = []
    dev.show = lambda colors, force=False: count.append(1) or True  # type: ignore[method-assign]
    runner.run(dev, effects.make("rainbow-wave", LEDS, effects.Params()), fps=500, duration=1.0,
               clock=clock, sleep=clock.sleep, log=lambda _m: None)
    assert len(count) <= runner.MAX_FPS + 1


def test_repeated_io_errors_stop_the_run():
    dev, _ = make_device()
    clock = FakeClock()

    def boom(colors, force=False):
        raise OSError(5, "Input/output error")

    dev.show = boom  # type: ignore[method-assign]
    logs: list[str] = []
    code = runner.run(dev, effects.make("rainbow-wave", LEDS, effects.Params()), clock=clock,
                      sleep=clock.sleep, log=logs.append)
    assert code == 1 and len(logs) == runner.MAX_CONSECUTIVE_ERRORS


# --- saved setting and CLI -------------------------------------------------------


def test_setting_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    s = config.Setting("gradient-wave", ["ff0080", "0080ff"], speed=7, brightness=60, fps=20)
    config.save(s, p)
    assert config.load(p) == s


def test_load_rejects_unknown_effect(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('effect = "disco"\ncolors = ["ffffff"]\n')
    with pytest.raises(ValueError):
        config.load(p)


def test_cli_effect_uses_effect_defaults_and_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    args = bifrost_cli.build_parser().parse_args(["effect", "swap", "--speed", "3"])
    s = bifrost_cli._setting_from_args(args)
    assert s.effect == "swap" and s.colors == ["ff0000", "0000ff"] and s.speed == 3
    assert config.path() == tmp_path / "acer-bifrost-rgb" / "config.toml"


def test_cli_lamps_requires_six_colours():
    with pytest.raises(SystemExit):
        bifrost_cli.build_parser().parse_args(["lamps", "ff0000", "00ff00"])


def test_service_unit_runs_apply():
    unit = bifrost_cli.service_unit()
    assert "acer-bifrost-rgb apply" in unit and "Restart=on-failure" in unit
