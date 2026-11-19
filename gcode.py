"""Pure G-code helpers for the doctor blade controller."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable


_NUMBER_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_BED_RE = re.compile(
    rf"\bB:\s*(?P<current>{_NUMBER_RE})(?:\s*/\s*(?P<target>{_NUMBER_RE}))?",
    re.IGNORECASE,
)
_BED_POWER_RE = re.compile(r"\bB@:\s*(?P<power>\d+)", re.IGNORECASE)
_X_POS_RE = re.compile(rf"(?:^|\s)X:\s*(?P<x>{_NUMBER_RE})(?:\s|$)", re.IGNORECASE)
_X_STEPS_RE = re.compile(
    rf"(?:^|\s)M92\b[^\r\n]*?(?:^|\s)X\s*(?P<x>{_NUMBER_RE})(?:\s|$)",
    re.IGNORECASE,
)
_X_MIN_ENDSTOP_RE = re.compile(
    r"^\s*x[_ -]?min\s*:\s*(?P<state>open|triggered)\s*$",
    re.IGNORECASE,
)


def _finite(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def format_gcode_number(value: float) -> str:
    """Format Marlin numeric parameters compactly while preserving precision."""
    number = _finite(value, "G-code value")
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def feedrate_mm_min(speed_mm_s: float) -> float:
    """Convert mm/s to Marlin feedrate units, mm/min."""
    speed = _finite(speed_mm_s, "Speed")
    if speed <= 0:
        raise ValueError("Speed must be greater than zero.")
    return speed * 60.0


def cmd_move_x(x_mm: float, speed_mm_s: float) -> str:
    """Generate an absolute X move command."""
    return f"G1 X{format_gcode_number(x_mm)} F{format_gcode_number(feedrate_mm_min(speed_mm_s))}"


def cmd_move_x_relative(delta_mm: float, speed_mm_s: float) -> str:
    """Generate an X move for use while Marlin is in relative-positioning mode."""
    return (
        f"G1 X{format_gcode_number(delta_mm)} "
        f"F{format_gcode_number(feedrate_mm_min(speed_mm_s))}"
    )


def staged_home_pretravel(
    estimated_distance_mm: float,
    safety_margin_mm: float,
) -> float:
    """Return the fast pre-homing distance, leaving the requested slow zone."""
    estimated_distance = _finite(estimated_distance_mm, "Estimated home distance")
    safety_margin = _finite(safety_margin_mm, "Homing safety margin")
    if estimated_distance < 0:
        raise ValueError("Estimated home distance cannot be negative.")
    if safety_margin <= 0:
        raise ValueError("Homing safety margin must be greater than zero.")
    return max(0.0, estimated_distance - safety_margin)


def cmd_accel(accel_mm_s2: float) -> str:
    """Generate a Marlin travel acceleration command."""
    acceleration = _finite(accel_mm_s2, "Acceleration")
    if acceleration <= 0:
        raise ValueError("Acceleration must be greater than zero.")
    return f"M204 T{format_gcode_number(acceleration)}"


def cmd_bed_set(temp_c: float) -> str:
    """Generate a non-blocking bed temperature set command."""
    temperature = _finite(temp_c, "Temperature")
    if temperature < 0:
        raise ValueError("Temperature cannot be negative.")
    return f"M140 S{format_gcode_number(temperature)}"


def cmd_bed_wait(temp_c: float) -> str:
    """Generate a blocking bed temperature set-and-wait command."""
    temperature = _finite(temp_c, "Temperature")
    if temperature < 0:
        raise ValueError("Temperature cannot be negative.")
    return f"M190 S{format_gcode_number(temperature)}"


def cmd_steps_x(steps_per_mm: float) -> str:
    """Generate an X steps/mm calibration command."""
    steps = _finite(steps_per_mm, "Steps/mm")
    if steps <= 0:
        raise ValueError("Steps/mm must be greater than zero.")
    return f"M92 X{format_gcode_number(steps)}"


def cmd_dwell(seconds: float) -> str:
    """Generate a dwell command in seconds."""
    duration = _finite(seconds, "Dwell time")
    if duration < 0:
        raise ValueError("Dwell time cannot be negative.")
    return f"G4 S{format_gcode_number(duration)}"


def parse_bed_temp(line: str) -> tuple[float, float | None] | None:
    """Parse current and target bed temperatures from an M105 response."""
    match = _BED_RE.search(line)
    if not match:
        return None
    current = float(match.group("current"))
    target_text = match.group("target")
    target = float(target_text) if target_text is not None else None
    return current, target


def parse_bed_power(line: str) -> int | None:
    """Parse Marlin's bed heater PWM value (B@, 0..127) from an M105 response."""
    match = _BED_POWER_RE.search(line)
    if not match:
        return None
    return int(match.group("power"))


def response_reports_bed(lines: Iterable[str]) -> bool:
    """Return True if an M105 response contains a bed temperature (B:)."""
    return any(parse_bed_temp(line) is not None for line in lines)


def parse_x_position(line: str) -> float | None:
    """Parse X position from an M114 response."""
    match = _X_POS_RE.search(line)
    if not match:
        return None
    return float(match.group("x"))


def parse_x_steps(line: str) -> float | None:
    """Parse X steps/mm from an M92 line reported by M92 or M503."""
    match = _X_STEPS_RE.search(line)
    if not match:
        return None
    return float(match.group("x"))


def parse_x_min_endstop(line: str) -> bool | None:
    """Parse an M119 X-min line; True means triggered, False means open."""
    match = _X_MIN_ENDSTOP_RE.match(line)
    if not match:
        return None
    return match.group("state").lower() == "triggered"


def parse_x_min_endstop_response(lines: Iterable[str]) -> bool | None:
    """Return the last X-min state found in a multiline M119 response."""
    state: bool | None = None
    for line in lines:
        parsed = parse_x_min_endstop(line)
        if parsed is not None:
            state = parsed
    return state


def validate_x_min_open_response(lines: Iterable[str]) -> None:
    """Reject homing unless M119 explicitly reports the X-min switch open."""
    state = parse_x_min_endstop_response(lines)
    if state is None:
        raise ValueError(
            "Homing blocked: M119 did not report x_min. Check the firmware and wiring."
        )
    if state:
        raise ValueError(
            "Homing blocked: X-min is already TRIGGERED. Release or inspect the switch."
        )


def validate_x_min_released_response(
    lines: Iterable[str],
    release_distance_mm: float,
) -> None:
    """Reject the post-homing state unless the X-min lever is released again."""
    state = parse_x_min_endstop_response(lines)
    if state is None:
        raise ValueError(
            "Homing not confirmed: M119 did not report x_min after the release move."
        )
    if state:
        raise ValueError(
            "Homing not confirmed: X-min is still TRIGGERED after moving "
            f"{format_gcode_number(release_distance_mm)} mm away from the switch. "
            "Check that the lever is free and not bent, and inspect the switch wiring."
        )
