"""Filter only MQTT notification lifecycles using durable car-event links."""

import json
import logging
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any

from peewee import PeeweeException

from frigate.models import VehicleVisit, VehicleVisitEvent

logger = logging.getLogger(__name__)

LINK_WAIT = 3.0
POLL_INTERVAL = 0.1
MAX_STATE = 4096
COVERAGE_TTL = 12 * 3600
REPEAT_REASONS = {
    "stationary_visual_match",
    "recent_visual_match",
    "plate_and_visual_match",
}


@dataclass(frozen=True)
class VehicleLink:
    visit_id: str
    repeated: bool


def lookup_links(camera: str, ids: list[str]) -> dict[str, VehicleLink]:
    """Read persisted live decisions, never infer identity in the MQTT layer."""
    rows = (
        VehicleVisitEvent.select(
            VehicleVisitEvent.event_id,
            VehicleVisitEvent.visit_id,
            VehicleVisitEvent.match_reason,
            VehicleVisit.closed_at,
        )
        .join(VehicleVisit, on=(VehicleVisitEvent.visit_id == VehicleVisit.id))
        .where((VehicleVisitEvent.event_id << ids) & (VehicleVisit.camera == camera))
        .dicts()
    )
    return {
        row["event_id"]: VehicleLink(
            row["visit_id"],
            row["match_reason"] in REPEAT_REASONS
            and row["event_id"] != row["visit_id"]
            and row["closed_at"] is None,
        )
        for row in rows
    }


@dataclass
class Message:
    topic: str
    payload: str
    data: dict
    retain: bool
    deadline: float

    @property
    def after(self) -> dict:
        return self.data["after"]

    @property
    def key(self) -> tuple[str, str, str]:
        return self.topic, self.after["camera"], self.after["id"]

    @property
    def car_ids(self) -> list[str]:
        if self.topic == "events":
            return [self.after["id"]] if self.after.get("label") == "car" else []
        data = self.after.get("data")
        if not isinstance(data, dict):
            return []
        objects = data.get("objects")
        ids = data.get("detections")
        if (
            isinstance(objects, list)
            and objects
            and all(label in ("car", "car-verified") for label in objects)
            and data.get("audio") == []
            and isinstance(ids, list)
            and ids
            and all(isinstance(event_id, str) for event_id in ids)
        ):
            return list(dict.fromkeys(ids))
        return []

    @property
    def scope(self) -> tuple[str, frozenset[str]]:
        if self.topic == "events":
            severity = self.after.get("max_severity")
            zones = self.after.get("entered_zones", [])
        else:
            severity = self.after.get("severity")
            zones = self.after.get("data", {}).get("zones", [])
        return str(severity), frozenset(zone for zone in zones if isinstance(zone, str))


class VehicleNotificationFilter:
    """Keep MQTT lifecycles coherent; only suppress confidently covered repeats."""

    def __init__(
        self,
        send: Callable[[str, Any, bool], bool],
        lookup: Callable[[str, list[str]], dict[str, VehicleLink]] = lookup_links,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.send = send
        self.lookup = lookup
        self.clock = clock
        # True = a new message reached the MQTT client; False = withheld.
        self.lifecycle: OrderedDict[tuple[str, str, str], bool] = OrderedDict()
        self.coverage: OrderedDict[
            tuple[str, str, str, str], tuple[float, frozenset[str]]
        ] = OrderedDict()

    def _remember(self, message: Message, visible: bool) -> None:
        self.lifecycle[message.key] = visible
        self.lifecycle.move_to_end(message.key)
        while len(self.lifecycle) > MAX_STATE:
            self.lifecycle.popitem(last=False)

    def _covered(self, message: Message, link: VehicleLink) -> bool:
        severity, zones = message.scope
        key = (message.topic, message.after["camera"], link.visit_id, severity)
        previous = self.coverage.get(key)
        return (
            link.repeated
            and previous is not None
            and self.clock() - previous[0] <= COVERAGE_TTL
            and zones.issubset(previous[1])
        )

    def _record(self, message: Message, links: dict[str, VehicleLink]) -> None:
        if not links:
            return
        severity, zones = message.scope
        now = self.clock()
        for link in links.values():
            key = (message.topic, message.after["camera"], link.visit_id, severity)
            previous = self.coverage.get(key)
            if previous is not None and now - previous[0] <= COVERAGE_TTL:
                covered = zones | previous[1]
            else:
                covered = zones
            self.coverage[key] = (now, covered)
            self.coverage.move_to_end(key)
        while len(self.coverage) > MAX_STATE:
            self.coverage.popitem(last=False)

    def _publish(self, message: Message, links: dict[str, VehicleLink]) -> None:
        visible = self.lifecycle.get(message.key)
        kind = message.data["type"]
        if visible is False and kind != "new":
            # Consumers never saw this native ID. Open its lifecycle before
            # sending updates, including a newly significant mixed Review.
            after = {**message.after, "end_time": None}
            before = dict(after)
            if message.topic == "events":
                before.update(
                    false_positive=True,
                    entered_zones=[],
                    current_zones=[],
                    max_severity=None,
                )
            new = {"type": "new", "before": before, "after": after}
            if not self.send(message.topic, json.dumps(new), message.retain):
                return
            self._remember(message, True)
            self._record(message, links)
            if kind != "end":
                return
        if self.send(message.topic, message.payload, message.retain):
            self._remember(message, True)
            self._record(message, links)

    def handle(self, message: Message, *, expired: bool = False) -> bool:
        """Return False only while awaiting an initial persisted link."""
        visible = self.lifecycle.get(message.key)
        ids = message.car_ids
        links: dict[str, VehicleLink] = {}
        if ids:
            try:
                links = self.lookup(message.after["camera"], ids)
            except PeeweeException:
                # Failed classification is not evidence of a duplicate.
                logger.exception("Vehicle MQTT lookup failed for %s", message.key)
                self._publish(message, {})
                return True
            if visible is not True and len(links) != len(ids) and not expired:
                return False
            if (
                visible is not True
                and len(links) == len(ids)
                and all(self._covered(message, link) for link in links.values())
            ):
                self._remember(message, False)
                logger.debug("Suppress repeated PTZ car MQTT message %s", message.key)
                return True
        self._publish(message, links)
        return True


class VehicleMqttPublisher:
    """Resolve car decisions off the realtime and interprocess publisher threads."""

    def __init__(self, config: Any, send: Callable[[str, Any, bool], bool]) -> None:
        self.config = config
        self.filter = VehicleNotificationFilter(send)
        self.queue: Queue[Message] = Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def submit(self, topic: str, payload: Any, retain: bool) -> bool:
        """Enqueue relevant native messages; return False for normal MQTT."""
        if topic not in ("events", "reviews") or retain:
            return False
        try:
            data = json.loads(payload)
            after = data["after"]
            camera = self.config.cameras.get(after["camera"])
            if (
                camera is None
                or not camera.onvif.autotracking.enabled_in_config
                or not isinstance(after["id"], str)
                or data["type"] not in ("new", "update", "end")
                or (topic == "events" and after.get("label") != "car")
            ):
                return False
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

        # All Review messages on that camera share the same ordered path,
        # since a car-only segment can later contain people or audio.
        message = Message(topic, payload, data, retain, time.monotonic() + LINK_WAIT)
        with self._lock:
            if self._stop.is_set():
                return False
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="vehicle_mqtt", daemon=True
                )
                self._worker.start()
            self.queue.put_nowait(message)
        return True

    def _run(self) -> None:
        pending: dict[tuple[str, str, str], deque[Message]] = {}
        while not self._stop.is_set() or pending or not self.queue.empty():
            try:
                message = self.queue.get(timeout=POLL_INTERVAL)
                pending.setdefault(message.key, deque()).append(message)
                # Bound each intake pass so busy cameras cannot starve decisions.
                for _ in range(255):
                    message = self.queue.get_nowait()
                    pending.setdefault(message.key, deque()).append(message)
            except Empty:
                pass
            for key, messages in list(pending.items()):
                # A person/audio update must not wait for a pending car lookup.
                mixed_waiting = any(not item.car_ids for item in messages)
                while messages:
                    item = messages[0]
                    expired = (
                        self._stop.is_set()
                        or mixed_waiting
                        or time.monotonic() >= item.deadline
                    )
                    try:
                        consumed = self.filter.handle(item, expired=expired)
                    except Exception:
                        # Keep the notification path alive on unexpected data
                        # or database failures, using the original payload.
                        logger.exception("Vehicle MQTT filter failed for %s", key)
                        try:
                            self.filter._publish(item, {})
                        except Exception:
                            logger.exception("Failed to publish MQTT message %s", key)
                        consumed = True
                    if not consumed:
                        break
                    messages.popleft()
                if not messages:
                    del pending[key]

    def stop(self) -> None:
        """Drain pending messages before disconnecting MQTT."""
        with self._lock:
            self._stop.set()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=5)
