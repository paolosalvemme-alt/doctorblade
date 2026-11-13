from __future__ import annotations

import math

import pytest

from diagnostics import (
    BedHeatingWatch,
    bed_power_percent,
    classify_bed_reading,
    explain_marlin_message,
)
from gcode import parse_bed_power, response_reports_bed


def test_bed_power_percent_scales_marlin_pwm() -> None:
    assert bed_power_percent(0) == 0.0
    assert bed_power_percent(127) == 100.0
    assert bed_power_percent(200) == 100.0
    assert bed_power_percent(-5) == 0.0
    with pytest.raises(ValueError):
        bed_power_percent(math.nan)


def test_parse_bed_power_from_m105() -> None:
    assert parse_bed_power("ok T:20.0 /0.0 B:43.2 /60.0 @:0 B@:127") == 127
    assert parse_bed_power("ok T:20.0 /0.0 B:43.2 /60.0 @:0") is None


def test_response_reports_bed_detects_missing_bed_heater() -> None:
    assert response_reports_bed(["ok T:20.0 /0.0 B:21.0 /0.0 @:0 B@:0"]) is True
    assert response_reports_bed(["ok T:20.0 /0.0 @:0"]) is False
    assert response_reports_bed([]) is False


@pytest.mark.parametrize("reading", [21.0, 0.0, 90.0])
def test_plausible_thermistor_reading_has_no_fault(reading: float) -> None:
    assert classify_bed_reading(reading) is None


def test_open_thermistor_points_to_thb_connector() -> None:
    fault = classify_bed_reading(-14.0)
    assert fault is not None
    assert "disconnected" in fault
    assert "PC4" in fault


def test_shorted_thermistor_is_reported() -> None:
    fault = classify_bed_reading(250.0)
    assert fault is not None
    assert "short" in fault


def test_non_finite_reading_is_reported() -> None:
    assert classify_bed_reading(math.nan) is not None


@pytest.mark.parametrize(
    ("line", "keyword"),
    [
        ("Error:MINTEMP triggered, system stopped! Heater_ID: bed", "THB"),
        ("Error:MAXTEMP triggered, system stopped! Heater_ID: bed", "MAXTEMP"),
        ("Error:Heating failed, system stopped! Heater_ID: bed", "HB screw terminal"),
        ("Error:Thermal Runaway, system stopped! Heater_ID: bed", "Thermal runaway"),
        ("Error:Homing Failed", "X-DIAG"),
        ('echo:Unknown command: "M999X"', "Unknown command"),
    ],
)
def test_marlin_errors_get_operator_hints(line: str, keyword: str) -> None:
    hint = explain_marlin_message(line)
    assert hint is not None
    assert keyword in hint


def test_unrelated_line_has_no_hint() -> None:
    assert explain_marlin_message("ok T:20.0 /0.0 B:21.0 /0.0") is None


def test_heating_watch_warns_once_when_bed_does_not_heat() -> None:
    watch = BedHeatingWatch(period_s=120.0, min_rise_c=2.0)
    assert watch.update(0.0, 21.0, 60.0) is None
    assert watch.update(60.0, 21.5, 60.0) is None
    warning = watch.update(121.0, 22.0, 60.0)
    assert warning is not None
    assert "HB" in warning
    assert watch.update(200.0, 22.0, 60.0) is None


def test_heating_watch_accepts_a_bed_that_warms_up() -> None:
    watch = BedHeatingWatch(period_s=120.0, min_rise_c=2.0)
    for step in range(20):
        assert watch.update(step * 30.0, 21.0 + step * 1.5, 60.0) is None


def test_heating_watch_ignores_heater_off_and_near_target() -> None:
    watch = BedHeatingWatch(period_s=10.0, min_rise_c=2.0)
    assert watch.update(0.0, 21.0, 0.0) is None
    assert watch.update(100.0, 21.0, 0.0) is None
    assert watch.update(0.0, 58.0, 60.0) is None
    assert watch.update(100.0, 58.0, 60.0) is None
    assert watch.update(0.0, 21.0, None) is None


def test_heating_watch_restarts_when_target_changes() -> None:
    watch = BedHeatingWatch(period_s=100.0, min_rise_c=2.0)
    assert watch.update(0.0, 21.0, 60.0) is None
    assert watch.update(90.0, 21.0, 70.0) is None
    assert watch.update(150.0, 21.0, 70.0) is None
    assert watch.update(191.0, 21.0, 70.0) is not None
