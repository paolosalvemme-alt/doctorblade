"""Pure hardware-diagnostic helpers for commissioning the doctor blade coater.

Nothing in this module talks to the serial port or the GUI, so every rule can
be unit-tested without an SKR board, heater, thermistor, or endstop attached.
The pin names refer to the BIGTREETECH SKR Mini E3 V3.0 pinout:

- X-STOP connector: GND + PC0 (X-min endstop signal)
- HB screw terminal: bed heater output switched by PC9
- THB connector: GND + PC4 (bed thermistor)
"""

from __future__ import annotations

from dataclasses import dataclass
import math


# A disconnected 100k NTC reads far below room temperature in Marlin; a shorted
# one reads far above any plausible bed temperature for this machine.
THERMISTOR_OPEN_BELOW_C = -5.0
THERMISTOR_SHORT_ABOVE_C = 150.0

# Application-side heating watch. Marlin's own WATCH_BED_TEMP (default 60 s /
# 2 deg C) remains the primary protection; this check only explains the fault.
HEATING_WATCH_PERIOD_S = 120.0
HEATING_WATCH_MIN_RISE_C = 2.0
HEATING_WATCH_ACTIVE_GAP_C = 5.0

MARLIN_MAX_PWM = 127.0


def bed_power_percent(raw_pwm: int | float) -> float:
    """Convert Marlin's B@ heater PWM value (0..127) to a percentage."""
    value = float(raw_pwm)
    if not math.isfinite(value):
        raise ValueError("Heater PWM must be a finite number.")
    return max(0.0, min(100.0, value * 100.0 / MARLIN_MAX_PWM))


def classify_bed_reading(current_c: float) -> str | None:
    """Return a thermistor fault description, or None for a plausible reading."""
    if not math.isfinite(current_c):
        return "Bed temperature reading is not a number."
    if current_c < THERMISTOR_OPEN_BELOW_C:
        return (
            f"Bed thermistor reads {current_c:.1f} deg C: probably disconnected or "
            "broken. Check the two thin thermistor wires on the THB connector "
            "(GND + PC4)."
        )
    if current_c > THERMISTOR_SHORT_ABOVE_C:
        return (
            f"Bed thermistor reads {current_c:.1f} deg C: probably short-circuited "
            "or the wrong TEMP_SENSOR_BED type is configured in Marlin."
        )
    return None


_MARLIN_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("mintemp",),
        "MINTEMP: Marlin sees an implausibly low bed temperature. The bed "
        "thermistor is disconnected, broken, or plugged into the wrong connector. "
        "It must be on THB (GND + PC4), not TH0. Reset the board after fixing it.",
    ),
    (
        ("maxtemp",),
        "MAXTEMP: the bed temperature exceeded BED_MAXTEMP, or the thermistor is "
        "short-circuited. Switch off the power supply and inspect the heater and "
        "thermistor wiring before resetting the board.",
    ),
    (
        ("heating failed", "heating_failed"),
        "Heating failed: Marlin commanded the bed heater but the temperature did "
        "not rise. Check that the pad's heater wires are in the HB screw terminal, "
        "that the pad voltage matches the power supply, and that the thermistor "
        "is taped or bonded to the heated plate.",
    ),
    (
        ("thermal runaway",),
        "Thermal runaway: the bed temperature fell away from the target while "
        "heating. Check the heater terminals, the thermistor contact with the "
        "plate, and the power supply. Reset the board after fixing it.",
    ),
    (
        ("homing failed", "endstop not released", "endstop not hit"),
        "Homing failed: the X-min endstop was not detected as expected. Use the "
        "live endstop monitor and check the X-STOP connector (GND + PC0) and that "
        "the X-DIAG jumper is removed.",
    ),
    (
        ("unknown command",),
        "Unknown command: this Marlin build does not support the command. Check "
        "the firmware configuration.",
    ),
)


def explain_marlin_message(line: str) -> str | None:
    """Return an operator-oriented explanation of a Marlin error line."""
    lowered = line.lower()
    for keywords, hint in _MARLIN_HINTS:
        if any(keyword in lowered for keyword in keywords):
            return hint
    return None


@dataclass(slots=True)
class BedHeatingWatch:
    """Detect a bed that is commanded to heat but does not warm up.

    Feed every temperature report through :meth:`update`. A warning is returned
    once per heating attempt when the bed rose less than ``min_rise_c`` within
    ``period_s`` while the target was well above the current temperature.
    """

    period_s: float = HEATING_WATCH_PERIOD_S
    min_rise_c: float = HEATING_WATCH_MIN_RISE_C
    active_gap_c: float = HEATING_WATCH_ACTIVE_GAP_C
    _start_time: float | None = None
    _start_temp: float | None = None
    _target: float | None = None
    _warned: bool = False

    def reset(self) -> None:
        self._start_time = None
        self._start_temp = None
        self._target = None
        self._warned = False

    def update(
        self,
        now_s: float,
        current_c: float,
        target_c: float | None,
    ) -> str | None:
        if target_c is None or not math.isfinite(current_c):
            return None
        if target_c <= 0 or target_c - current_c < self.active_gap_c:
            # Heater off or close to target: nothing to watch.
            self.reset()
            return None
        if self._target != target_c or self._start_time is None:
            self._target = target_c
            self._start_time = now_s
            self._start_temp = current_c
            self._warned = False
            return None
        assert self._start_temp is not None
        if current_c - self._start_temp >= self.min_rise_c:
            # Heating confirmed; restart the window from the new temperature.
            self._start_time = now_s
            self._start_temp = current_c
            return None
        if self._warned or now_s - self._start_time < self.period_s:
            return None
        self._warned = True
        return (
            f"The bed target is {target_c:g} deg C but the temperature rose less "
            f"than {self.min_rise_c:g} deg C in {self.period_s:g} s "
            f"({self._start_temp:.1f} -> {current_c:.1f} deg C). The heater has "
            "been switched off. Check the HB terminal wiring, the power supply "
            "voltage, and the thermistor position."
        )
