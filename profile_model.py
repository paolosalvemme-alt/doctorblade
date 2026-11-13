"""JSON-serializable coating profile model."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any


def _json_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0", ""}:
            return False
    return default


@dataclass(slots=True)
class CoatingSegment:
    target_x_mm: float
    speed_mm_s: float
    acceleration_mm_s2: float
    dwell_s: float
    bed_temp_c: float | None = None
    wait_for_temperature: bool = False

    def validate(self, travel_limit_mm: float) -> None:
        if not math.isfinite(travel_limit_mm) or travel_limit_mm <= 0:
            raise ValueError("Travel limit must be greater than zero.")
        values = {
            "Target X": self.target_x_mm,
            "Segment speed": self.speed_mm_s,
            "Segment acceleration": self.acceleration_mm_s2,
            "Segment dwell": self.dwell_s,
        }
        if self.bed_temp_c is not None:
            values["Segment bed temperature"] = self.bed_temp_c
        for label, value in values.items():
            if not math.isfinite(value):
                raise ValueError(f"{label} must be a finite number.")
        if not 0 <= self.target_x_mm <= travel_limit_mm:
            raise ValueError(
                f"Target X {self.target_x_mm:g} mm is outside 0-{travel_limit_mm:g} mm."
            )
        if self.speed_mm_s <= 0:
            raise ValueError("Segment speed must be greater than zero.")
        if self.acceleration_mm_s2 <= 0:
            raise ValueError("Segment acceleration must be greater than zero.")
        if self.dwell_s < 0:
            raise ValueError("Segment dwell cannot be negative.")
        if self.bed_temp_c is not None and self.bed_temp_c < 0:
            raise ValueError("Segment bed temperature cannot be negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_x_mm": self.target_x_mm,
            "speed_mm_s": self.speed_mm_s,
            "acceleration_mm_s2": self.acceleration_mm_s2,
            "dwell_s": self.dwell_s,
            "bed_temp_c": self.bed_temp_c,
            "wait_for_temperature": self.wait_for_temperature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoatingSegment":
        bed_temp = (
            None if data.get("bed_temp_c") in (None, "") else float(data["bed_temp_c"])
        )
        return cls(
            target_x_mm=float(data["target_x_mm"]),
            speed_mm_s=float(data["speed_mm_s"]),
            acceleration_mm_s2=float(data["acceleration_mm_s2"]),
            dwell_s=float(data.get("dwell_s", 0.0)),
            bed_temp_c=bed_temp,
            wait_for_temperature=(
                _json_bool(data.get("wait_for_temperature", False))
                if bed_temp is not None
                else False
            ),
        )


@dataclass(slots=True)
class CoatingProfile:
    name: str = "Untitled profile"
    segments: list[CoatingSegment] = field(default_factory=list)

    def validate(self, travel_limit_mm: float) -> None:
        if not self.segments:
            raise ValueError("Profile has no segments.")
        for index, segment in enumerate(self.segments, start=1):
            try:
                segment.validate(travel_limit_mm)
            except ValueError as exc:
                raise ValueError(f"Segment {index}: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoatingProfile":
        segments = [CoatingSegment.from_dict(item) for item in data.get("segments", [])]
        return cls(name=str(data.get("name", "Untitled profile")), segments=segments)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "CoatingProfile":
        return cls.from_dict(json.loads(text))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CoatingProfile":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
