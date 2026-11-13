"""Calibration math for the doctor blade X axis."""

from __future__ import annotations

import math


def calculate_new_steps(
    current_steps_per_mm: float,
    commanded_distance_mm: float,
    measured_distance_mm: float,
) -> float:
    """Calculate corrected X steps/mm from an external stroke measurement."""
    if not math.isfinite(current_steps_per_mm):
        raise ValueError("Current steps/mm must be a finite number.")
    if not math.isfinite(commanded_distance_mm):
        raise ValueError("Commanded distance must be a finite number.")
    if not math.isfinite(measured_distance_mm):
        raise ValueError("Measured distance must be a finite number.")
    if current_steps_per_mm <= 0:
        raise ValueError("Current steps/mm must be greater than zero.")
    if commanded_distance_mm <= 0:
        raise ValueError("Commanded distance must be greater than zero.")
    if measured_distance_mm <= 0:
        raise ValueError("Measured distance must be greater than zero.")
    return current_steps_per_mm * commanded_distance_mm / measured_distance_mm
