"""Shared lifecycle and health contracts for runtime sensors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from ..evidence import EvidenceSource


class SensorError(ValueError):
    """Base error for runtime sensor lifecycle operations."""


class SensorStartError(SensorError):
    """Raised when a runtime sensor cannot start safely."""

    code = "SENSOR_START_FAILED"


class SensorAlreadyRunningError(SensorStartError):
    """Raised when a second observer would be created for one sensor."""

    code = "ALREADY_RUNNING"


class SensorStopError(SensorError):
    """Raised when a runtime sensor cannot stop safely."""

    code = "SENSOR_STOP_FAILED"


class SensorStatus(StrEnum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class SensorHealth:
    sensor: EvidenceSource
    status: SensorStatus
    checked_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sensor", EvidenceSource(self.sensor))
        object.__setattr__(self, "status", SensorStatus(self.status))
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise SensorError("checked_at must be timezone-aware")
        object.__setattr__(
            self,
            "checked_at",
            self.checked_at.astimezone(timezone.utc),
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "checked_at": self.checked_at.isoformat(),
            "sensor": self.sensor.value,
            "status": self.status.value,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


__all__ = [
    "SensorAlreadyRunningError",
    "SensorError",
    "SensorHealth",
    "SensorStartError",
    "SensorStatus",
    "SensorStopError",
]
