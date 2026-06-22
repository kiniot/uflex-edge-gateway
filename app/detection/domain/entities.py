"""Domain entities and value objects for the Detection bounded context.

The edge is **thin in definitions, rich in detection**: it does not replicate the
backend's plan/routine/exercise model. It holds only the *execution* concepts it
needs to detect repetitions in real time and forward them to the backend (the
durable system of record).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MovementSample:
    """A single movement reading from the kit.

    Carries the active joint's absolute flexion ``angle`` (degrees, zero-offset
    calibrated by the firmware) plus an optional ``proximal_signal`` (proximal-
    segment yaw). The angle drives repetition detection now; the proximal signal
    is populated by the firmware but consumed only in Wave 2 (compensatory
    movement detection, §13.4).
    """

    serial_number: str
    angle: float
    recorded_at: datetime
    proximal_signal: Optional[float] = None


@dataclass
class ExecutionContext:
    """The active serie a kit is executing, hydrated from the backend.

    Correlated by ``session_id`` + ``serie_id`` and carrying the targets the edge
    needs to classify repetitions in real time. Lives in memory; re-fetched from
    ``GET /active/by-device/{serial}`` after a restart or serie change.
    """

    session_id: str
    serie_id: str
    target_rom: Optional[float] = None
    target_reps: Optional[int] = None
    movement_type: Optional[str] = None
    body_part: Optional[str] = None
    max_safe_angle: Optional[float] = None


@dataclass
class DetectedRepetition:
    """A repetition detected by the edge, pending durable forwarding to the backend.

    ``edge_sequence_id`` is the idempotency key (a UUID generated once at
    detection and reused on every retry); the backend deduplicates on it.
    """

    serial_number: str
    session_id: str
    serie_id: str
    edge_sequence_id: str
    achieved_rom: float
    peak_angle: float
    classification: str  # "good" | "incomplete" | "unsafe"
    met_target: bool
    unsafe: bool
    recorded_at: datetime
    forward_status: str = "PENDING"  # "PENDING" | "SENT"
    id: Optional[int] = None


@dataclass
class CompensatoryMovement:
    """A compensatory movement detected by the edge (detector deferred, §13.4).

    Modeled now so the forwarding pipeline and outbox are shape-complete; no
    producer exists until the enriched sample + detector land.
    """

    serial_number: str
    session_id: str
    serie_id: str
    edge_sequence_id: str
    type: str  # "ShoulderCompensation" | "TrunkCompensation"
    detected_at: datetime
    forward_status: str = "PENDING"
    id: Optional[int] = None
