"""Persistent user settings for the Windows desktop app."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


APP_NAME = "DoctorBladeControllerV305"


@dataclass(slots=True)
class AppSettings:
    last_com_port: str = ""
    baud_rate: int = 115200
    default_speed_mm_s: float = 5.0
    default_acceleration_mm_s2: float = 300.0
    travel_limit_mm: float = 200.0
    bed_safety_limit_c: float = 90.0
    allow_movement_before_homing: bool = False
    default_bed_temperature_c: float = 60.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        defaults = cls()

        def finite_float(key: str, default: float, *, positive: bool = False) -> float:
            try:
                value = float(data.get(key, default))
            except (TypeError, ValueError):
                return default
            if not math.isfinite(value):
                return default
            if positive and value <= 0:
                return default
            if not positive and value < 0:
                return default
            return value

        try:
            baud_rate = int(data.get("baud_rate", defaults.baud_rate))
        except (TypeError, ValueError):
            baud_rate = defaults.baud_rate
        if baud_rate <= 0:
            baud_rate = defaults.baud_rate

        allow_unhomed = data.get(
            "allow_movement_before_homing",
            defaults.allow_movement_before_homing,
        )
        if not isinstance(allow_unhomed, bool):
            allow_unhomed = defaults.allow_movement_before_homing

        return cls(
            last_com_port=str(data.get("last_com_port", defaults.last_com_port)),
            baud_rate=baud_rate,
            default_speed_mm_s=finite_float(
                "default_speed_mm_s",
                defaults.default_speed_mm_s,
                positive=True,
            ),
            default_acceleration_mm_s2=finite_float(
                "default_acceleration_mm_s2",
                defaults.default_acceleration_mm_s2,
                positive=True,
            ),
            travel_limit_mm=finite_float(
                "travel_limit_mm",
                defaults.travel_limit_mm,
                positive=True,
            ),
            bed_safety_limit_c=finite_float(
                "bed_safety_limit_c",
                defaults.bed_safety_limit_c,
            ),
            allow_movement_before_homing=allow_unhomed,
            default_bed_temperature_c=finite_float(
                "default_bed_temperature_c",
                defaults.default_bed_temperature_c,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _running_from_bundle() -> bool:
    return bool(getattr(sys, "frozen", False))


def default_settings_path() -> Path:
    """Choose an app-data settings path, falling back to the executable folder."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME / "settings.json"

    base = Path(sys.executable).parent if _running_from_bundle() else Path(__file__).parent
    return base / "settings.json"


class SettingsManager:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return AppSettings()
            return AppSettings.from_dict(data)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
