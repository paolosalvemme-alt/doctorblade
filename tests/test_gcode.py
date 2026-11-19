import math

import pytest

from gcode import (
    cmd_accel,
    cmd_bed_set,
    cmd_move_x,
    cmd_move_x_relative,
    cmd_steps_x,
    feedrate_mm_min,
    format_gcode_number,
    parse_bed_temp,
    parse_x_min_endstop,
    parse_x_min_endstop_response,
    parse_x_position,
    parse_x_steps,
    staged_home_pretravel,
    validate_x_min_open_response,
    validate_x_min_released_response,
)


def test_motion_commands_use_marlin_units_and_travel_acceleration() -> None:
    assert feedrate_mm_min(5.0) == 300.0
    assert cmd_move_x(12.5, 5.0) == "G1 X12.5 F300"
    assert cmd_move_x_relative(-80.0, 10.0) == "G1 X-80 F600"
    assert cmd_accel(300.0) == "M204 T300"


def test_staged_home_pretravel_reserves_the_slow_zone() -> None:
    assert staged_home_pretravel(120.0, 40.0) == 80.0
    assert staged_home_pretravel(40.0, 40.0) == 0.0
    assert staged_home_pretravel(20.0, 40.0) == 0.0

    with pytest.raises(ValueError):
        staged_home_pretravel(-1.0, 40.0)
    with pytest.raises(ValueError):
        staged_home_pretravel(100.0, 0.0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_never_formatted_as_gcode(value: float) -> None:
    with pytest.raises(ValueError):
        format_gcode_number(value)
    with pytest.raises(ValueError):
        cmd_bed_set(value)
    with pytest.raises(ValueError):
        cmd_steps_x(value)


def test_marlin_response_parsers() -> None:
    assert parse_bed_temp("ok T:20.0 /0.0 B:43.2 /60.0 @:0") == (43.2, 60.0)
    assert parse_x_position("X:12.345 Y:0.00 Z:0.00 E:0.00") == 12.345
    assert parse_x_steps("echo:  M92 X80.00 Y80.00 Z400.00 E93.00") == 80.0
    assert parse_x_steps("M92 X 100.25 Y80") == 100.25
    assert parse_x_min_endstop("x_min: open") is False
    assert parse_x_min_endstop("X-MIN: TRIGGERED") is True
    assert parse_x_min_endstop("y_min: open") is None


def test_invalid_positive_parameters_are_rejected() -> None:
    with pytest.raises(ValueError):
        feedrate_mm_min(0)
    with pytest.raises(ValueError):
        cmd_accel(-1)
    with pytest.raises(ValueError):
        cmd_steps_x(0)


def test_x_min_multiline_response_is_validated_before_homing() -> None:
    open_response = ["Reporting endstop status", "x_min: open", "ok"]
    triggered_response = ["x_min: TRIGGERED", "ok"]

    assert parse_x_min_endstop_response(open_response) is False
    assert parse_x_min_endstop_response(triggered_response) is True
    validate_x_min_open_response(open_response)

    with pytest.raises(ValueError, match="already TRIGGERED"):
        validate_x_min_open_response(triggered_response)
    with pytest.raises(ValueError, match="did not report x_min"):
        validate_x_min_open_response(["y_min: open", "ok"])


def test_released_response_accepts_open_switch_after_homing() -> None:
    validate_x_min_released_response(["x_min: open", "ok"], 5.0)


def test_released_response_rejects_pressed_or_missing_switch() -> None:
    with pytest.raises(ValueError, match="still TRIGGERED after moving 5 mm"):
        validate_x_min_released_response(["x_min: TRIGGERED", "ok"], 5.0)
    with pytest.raises(ValueError, match="did not report x_min"):
        validate_x_min_released_response(["ok"], 5.0)
