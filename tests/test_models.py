import math

import pytest

from calibration import calculate_new_steps
from profile_model import CoatingProfile, CoatingSegment
from settings_manager import AppSettings


def test_calibration_formula() -> None:
    assert calculate_new_steps(80.0, 100.0, 95.0) == pytest.approx(
        84.2105263158
    )


@pytest.mark.parametrize(
    "values",
    [
        (math.nan, 100.0, 100.0),
        (80.0, math.inf, 100.0),
        (80.0, 100.0, 0.0),
    ],
)
def test_calibration_rejects_invalid_measurements(
    values: tuple[float, float, float],
) -> None:
    with pytest.raises(ValueError):
        calculate_new_steps(*values)


def test_profile_round_trip_and_validation() -> None:
    profile = CoatingProfile(
        name="Test",
        segments=[
            CoatingSegment(
                target_x_mm=50.0,
                speed_mm_s=5.0,
                acceleration_mm_s2=200.0,
                dwell_s=1.0,
                bed_temp_c=60.0,
                wait_for_temperature=True,
            )
        ],
    )
    restored = CoatingProfile.from_json(profile.to_json())
    restored.validate(200.0)
    assert restored == profile


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_x_mm", math.nan),
        ("speed_mm_s", math.inf),
        ("acceleration_mm_s2", math.nan),
        ("dwell_s", math.inf),
        ("bed_temp_c", math.nan),
    ],
)
def test_profile_rejects_non_finite_values(field: str, value: float) -> None:
    segment = CoatingSegment(
        target_x_mm=50.0,
        speed_mm_s=5.0,
        acceleration_mm_s2=200.0,
        dwell_s=0.0,
        bed_temp_c=60.0,
    )
    setattr(segment, field, value)
    with pytest.raises(ValueError):
        segment.validate(200.0)


def test_settings_reject_malformed_or_unsafe_persisted_values() -> None:
    settings = AppSettings.from_dict(
        {
            "baud_rate": -1,
            "default_speed_mm_s": "not-a-number",
            "travel_limit_mm": math.nan,
            "allow_movement_before_homing": "false",
        }
    )
    defaults = AppSettings()
    assert settings.baud_rate == defaults.baud_rate
    assert settings.default_speed_mm_s == defaults.default_speed_mm_s
    assert settings.travel_limit_mm == defaults.travel_limit_mm
    assert settings.allow_movement_before_homing is False


def test_profile_parses_boolean_strings_and_normalizes_unused_wait_flag() -> None:
    waiting = CoatingSegment.from_dict(
        {
            "target_x_mm": 10,
            "speed_mm_s": 5,
            "acceleration_mm_s2": 100,
            "bed_temp_c": 60,
            "wait_for_temperature": "false",
        }
    )
    no_temperature = CoatingSegment.from_dict(
        {
            "target_x_mm": 10,
            "speed_mm_s": 5,
            "acceleration_mm_s2": 100,
            "bed_temp_c": None,
            "wait_for_temperature": True,
        }
    )
    assert waiting.wait_for_temperature is False
    assert no_temperature.wait_for_temperature is False

