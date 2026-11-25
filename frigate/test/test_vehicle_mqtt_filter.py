"""Regression tests for the native MQTT car notification filter."""

import base64
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from peewee import OperationalError
from playhouse.sqlite_ext import SqliteExtDatabase

from frigate.models import VehicleVisit, VehicleVisitEvent
from frigate.vehicle_visits.inspection import inspect_event
from frigate.vehicle_visits.mqtt_filter import (
    Message,
    VehicleLink,
    VehicleMqttPublisher,
    VehicleNotificationFilter,
    lookup_links,
)


def event_message(
    event_id, kind="new", camera="ptz", zones=(), severity="alert", label="car"
):
    after = {
        "id": event_id,
        "camera": camera,
        "label": label,
        "end_time": 200 if kind == "end" else None,
        "entered_zones": list(zones),
        "current_zones": list(zones),
        "max_severity": severity,
        "false_positive": False,
    }
    before = {**after, "false_positive": kind == "new"}
    data = {"type": kind, "before": before, "after": after}
    return Message("events", json.dumps(data), data, False, 0)


def review_message(
    review_id,
    ids,
    kind="new",
    objects=("car",),
    zones=(),
    severity="alert",
    audio=(),
):
    after = {
        "id": review_id,
        "camera": "ptz",
        "severity": severity,
        "end_time": 200 if kind == "end" else None,
        "data": {
            "detections": list(ids),
            "objects": list(objects),
            "zones": list(zones),
            "audio": list(audio),
        },
    }
    data = {"type": kind, "before": after, "after": after}
    return Message("reviews", json.dumps(data), data, False, 0)


class TestVehicleNotificationFilter(unittest.TestCase):
    def setUp(self):
        self.links = {
            "a": VehicleLink("a", False),
            "b": VehicleLink("a", True),
            "c": VehicleLink("c", False),
        }
        self.sent = []
        self.now = 0.0
        self.filter = VehicleNotificationFilter(self.send, self.lookup, lambda: self.now)

    def lookup(self, camera, ids):
        return {
            event_id: self.links[event_id] for event_id in ids if event_id in self.links
        }

    def send(self, topic, payload, retain):
        self.sent.append((topic, json.loads(payload), retain))
        return True

    def test_suppresses_entire_repeated_object_lifecycle(self):
        for kind in ("new", "update", "end"):
            self.assertTrue(self.filter.handle(event_message("a", kind)))
        for kind in ("new", "update", "end"):
            self.assertTrue(self.filter.handle(event_message("b", kind)))
        self.assertEqual(
            [data["type"] for _, data, _ in self.sent], ["new", "update", "end"]
        )
        self.assertTrue(all(data["after"]["id"] == "a" for _, data, _ in self.sent))

    def test_waits_for_live_link_and_fails_open_when_missing(self):
        message = event_message("unknown")
        self.assertFalse(self.filter.handle(message))
        self.assertFalse(self.sent)
        self.assertTrue(self.filter.handle(message, expired=True))
        self.assertEqual(self.sent[0][1], message.data)
        update = event_message("unknown", "update")
        self.assertTrue(self.filter.handle(update))
        self.assertEqual(self.sent[1][1], update.data)

    def test_missing_link_can_resolve_to_repeat_before_deadline(self):
        self.filter.handle(event_message("a"))
        message = event_message("pending")
        self.assertFalse(self.filter.handle(message))
        self.links["pending"] = VehicleLink("a", True)
        self.assertTrue(self.filter.handle(message))
        self.assertEqual(len(self.sent), 1)

    def test_new_car_and_ambiguous_match_are_not_hidden(self):
        self.filter.handle(event_message("a"))
        self.filter.handle(event_message("c"))
        self.links["ambiguous"] = VehicleLink("ambiguous", False)
        self.filter.handle(event_message("ambiguous"))
        self.assertEqual(
            [data["after"]["id"] for _, data, _ in self.sent],
            ["a", "c", "ambiguous"],
        )

    def test_first_repeat_after_restart_fails_open(self):
        self.filter.handle(event_message("b"))
        self.assertEqual(self.sent[0][1]["type"], "new")

    def test_expired_coverage_fails_open(self):
        self.filter.handle(event_message("a"))
        self.now = 12 * 3600 + 1
        self.filter.handle(event_message("b"))
        self.assertEqual(len(self.sent), 2)

    def test_failed_publish_does_not_establish_coverage(self):
        self.filter.send = lambda *_: False
        self.filter.handle(event_message("a"))
        self.filter.send = self.send
        self.filter.handle(event_message("b"))
        self.assertEqual(self.sent[0][1]["after"]["id"], "b")

    def test_lookup_failure_does_not_hide_detection(self):
        self.filter.lookup = lambda *_: (_ for _ in ()).throw(OperationalError("DB"))
        message = event_message("a")
        with self.assertLogs("frigate.vehicle_visits.mqtt_filter", level="ERROR"):
            self.assertTrue(self.filter.handle(message))
        self.assertEqual(self.sent[0][1], message.data)

    def test_new_zone_opens_previously_suppressed_lifecycle(self):
        self.filter.handle(event_message("a", zones=("driveway",)))
        self.filter.handle(event_message("b", zones=("driveway",)))
        self.filter.handle(event_message("b", "update", zones=("garage",)))
        self.filter.handle(event_message("b", "end", zones=("garage",)))
        self.assertEqual(
            [(data["after"]["id"], data["type"]) for _, data, _ in self.sent],
            [("a", "new"), ("b", "new"), ("b", "end")],
        )
        self.assertEqual(self.sent[1][1]["before"]["entered_zones"], [])

    def test_review_upgrade_and_mixed_review_remain_visible(self):
        self.filter.handle(review_message("r1", ["a"], severity="detection"))
        self.filter.handle(review_message("r2", ["b"], severity="detection"))
        self.filter.handle(review_message("r2", ["b"], "update"))
        self.filter.handle(review_message("r3", ["b"], severity="detection"))
        self.filter.handle(
            review_message("r3", ["b", "person"], "update", ("car", "person"))
        )
        self.filter.handle(
            review_message("r3", ["b", "person"], "end", ("car", "person"))
        )
        self.assertEqual(
            [(data["after"]["id"], data["type"]) for _, data, _ in self.sent],
            [("r1", "new"), ("r2", "new"), ("r3", "new"), ("r3", "end")],
        )
        self.assertIn("person", self.sent[2][1]["after"]["data"]["objects"])

    def test_review_with_new_second_car_is_not_hidden(self):
        self.filter.handle(review_message("r1", ["a"]))
        self.filter.handle(review_message("r2", ["b"]))
        self.filter.handle(review_message("r2", ["b", "c"], "update"))
        self.assertEqual(self.sent[-1][1]["type"], "new")
        self.assertEqual(self.sent[-1][1]["after"]["data"]["detections"], ["b", "c"])

    def test_review_audio_never_suppressed(self):
        self.filter.handle(review_message("r1", ["a"]))
        self.filter.handle(review_message("r2", ["b"], audio=("bark",)))
        self.assertEqual(len(self.sent), 2)

    def test_review_and_object_topics_have_independent_coverage(self):
        self.filter.handle(event_message("a"))
        self.filter.handle(review_message("r1", ["b"]))
        self.assertEqual([topic for topic, _, _ in self.sent], ["events", "reviews"])

    def test_late_significant_end_has_a_new_before_end(self):
        self.filter.handle(review_message("r1", ["a"]))
        self.filter.handle(review_message("r2", ["b"]))
        self.filter.handle(
            review_message("r2", ["b", "person"], "end", ("car", "person"))
        )
        self.assertEqual(
            [data["type"] for _, data, _ in self.sent], ["new", "new", "end"]
        )
        self.assertIsNone(self.sent[1][1]["after"]["end_time"])


class TestVehicleMqttPublisher(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            cameras={
                "ptz": SimpleNamespace(
                    onvif=SimpleNamespace(
                        autotracking=SimpleNamespace(enabled_in_config=True)
                    )
                ),
                "static": SimpleNamespace(
                    onvif=SimpleNamespace(
                        autotracking=SimpleNamespace(enabled_in_config=False)
                    )
                ),
            }
        )

    def test_passthrough_and_ordered_async_publication(self):
        done = threading.Event()
        sent = []

        def send(topic, payload, retain):
            sent.append(json.loads(payload))
            if len(sent) == 3:
                done.set()
            return True

        publisher = VehicleMqttPublisher(self.config, send)
        try:
            publisher.filter.lookup = lambda _, ids: {
                event_id: VehicleLink(event_id, False) for event_id in ids
            }
            person = event_message("p", label="person")
            static = event_message("s", camera="static")
            self.assertFalse(publisher.submit("events", person.payload, False))
            self.assertFalse(publisher.submit("events", static.payload, False))
            self.assertFalse(publisher.submit("ptz/car", "2", False))
            self.assertFalse(publisher.submit("events", "invalid", False))
            for kind in ("new", "update", "end"):
                message = event_message("a", kind)
                self.assertTrue(publisher.submit("events", message.payload, False))
            self.assertTrue(done.wait(2))
            self.assertEqual([data["type"] for data in sent], ["new", "update", "end"])
        finally:
            publisher.stop()

    def test_waiting_car_does_not_block_mixed_review(self):
        done = threading.Event()
        sent = []

        def send(topic, payload, retain):
            data = json.loads(payload)
            sent.append(data)
            if data["after"]["id"] == "human":
                done.set()
            return True

        publisher = VehicleMqttPublisher(self.config, send)
        try:
            publisher.filter.lookup = lambda *_: {}
            car = review_message("waiting", ["unlinked"])
            human = review_message("human", ["person"], objects=("person",))
            self.assertTrue(publisher.submit("reviews", car.payload, False))
            self.assertTrue(publisher.submit("reviews", human.payload, False))
            self.assertTrue(done.wait(1))
            self.assertEqual(sent[0]["after"]["id"], "human")
        finally:
            publisher.stop()


class TestVehicleLinkLookup(unittest.TestCase):
    def test_open_closed_and_camera_scope(self):
        db = SqliteExtDatabase(":memory:")
        models = [VehicleVisit, VehicleVisitEvent]
        with db.bind_ctx(models):
            db.connect()
            try:
                db.create_tables(models)
                VehicleVisit.create(id="a", camera="ptz", start_time=100, last_seen=110)
                for event_id, reason in (
                    ("a", "first_detection"),
                    ("b", "stationary_visual_match"),
                    ("c", "manual_merge"),
                ):
                    VehicleVisitEvent.create(
                        event_id=event_id,
                        visit_id="a",
                        match_reason=reason,
                        start_time=100,
                    )
                self.assertEqual(
                    lookup_links("ptz", ["a", "b", "c", "missing"]),
                    {
                        "a": VehicleLink("a", False),
                        "b": VehicleLink("a", True),
                        "c": VehicleLink("a", False),
                    },
                )
                self.assertEqual(lookup_links("other", ["b"]), {})
                VehicleVisit.update(closed_at=110).where(VehicleVisit.id == "a").execute()
                self.assertEqual(
                    lookup_links("ptz", ["b"]), {"b": VehicleLink("a", False)}
                )
            finally:
                db.close()

    def test_live_crop_is_used_before_thumbnail_file_exists(self):
        image = np.tile(
            np.array([30, 200, 30, 200, 30, 200, 30, 200, 30], dtype=np.uint8),
            (8, 1),
        )
        success, encoded = cv2.imencode(".png", image)
        self.assertTrue(success)
        event = SimpleNamespace(
            id="a",
            camera="ptz",
            data={"box": [0.2, 0.2, 0.7, 0.7]},
            sub_label=None,
            start_time=100,
            end_time=None,
        )
        with patch(
            "frigate.vehicle_visits.inspection.get_event_thumbnail_bytes"
        ) as disk:
            observation = inspect_event(event, base64.b64encode(encoded).decode())
            disk.assert_not_called()
        self.assertIsNotNone(observation.image_hash)
        self.assertEqual(observation.box, (0.2, 0.2, 0.7, 0.7))
