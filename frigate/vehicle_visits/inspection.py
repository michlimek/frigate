"""Extract comparable car features from stored Frigate events."""

import binascii
import logging
from datetime import UTC, datetime

import cv2
import numpy as np

from frigate.util.file import get_event_thumbnail_bytes
from frigate.vehicle_visits.matching import VehicleObservation

logger = logging.getLogger(__name__)


def event_timestamp(value) -> float:
    """Normalize Peewee epoch and datetime values."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.timestamp()
    return float(value)


def relative_box(value) -> tuple[float, float, float, float] | None:
    """Return a valid 0..1 relative box or None."""
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        box = tuple(float(n) for n in value)
    except (ValueError, TypeError):
        return None
    if not all(np.isfinite(n) and 0.0 <= n <= 1.0 for n in box):
        return None
    return box if box[0] < box[2] and box[1] < box[3] else None


def image_hash(image_bytes: bytes | None) -> int | None:
    """Compute the same 64-bit grayscale dHash used by visit matching."""
    if not image_bytes:
        return None
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    small = cv2.resize(image, (9, 8), interpolation=cv2.INTER_AREA)
    differences = (small[:, 1:] > small[:, :-1]).reshape(-1)
    bits = sum(int(bit) << i for i, bit in enumerate(differences))
    # Completely flat imagery is unreliable across different cars.
    return bits if 5 <= bits.bit_count() <= 59 else None


def inspect_event(event) -> VehicleObservation:
    """Inspect one event's own thumbnail, never the camera's current frame."""
    data = event.data if isinstance(event.data, dict) else {}
    plate = data.get("recognized_license_plate")
    if not plate and event.sub_label:
        # sub_label is not necessarily an LPR plate, do not guess.
        plate = None
    try:
        photo = get_event_thumbnail_bytes(event)
    except (ValueError, binascii.Error, OSError):
        logger.warning("Cannot read thumbnail for event %s", event.id)
        photo = None
    start = event_timestamp(event.start_time)
    end = event_timestamp(event.end_time) if event.end_time is not None else start
    return VehicleObservation(
        event_id=event.id,
        camera=event.camera,
        start_time=start,
        end_time=max(start, end),
        box=relative_box(data.get("box")),
        image_hash=image_hash(photo),
        license_plate=str(plate).strip().upper() if plate else None,
    )
