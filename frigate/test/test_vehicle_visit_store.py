"""Persistent vehicle-visit mapping regressions."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from playhouse.sqlite_ext import SqliteExtDatabase

from frigate.db.sqlitevecq import SqliteVecQueueDatabase
from frigate.models import Event, VehicleVisit, VehicleVisitEvent
from frigate.vehicle_visits.matching import VehicleObservation
from frigate.vehicle_visits.store import correct_vehicle_events, link_event_to_visit


class TestVehicleVisitStore(unittest.TestCase):
    BOX = (0.2, 0.2, 0.7, 0.7)

    def setUp(self):
        self.db = SqliteExtDatabase(":memory:")
        self.db.bind([Event, VehicleVisit, VehicleVisitEvent])
        self.db.connect()
        self.db.create_tables([Event, VehicleVisit, VehicleVisitEvent])

    def tearDown(self):
        self.db.drop_tables([VehicleVisitEvent, VehicleVisit, Event])
        self.db.close()

    def event(
        self,
        eid,
        at,
        digest=0x33CC001122334455,
        box=None,
        camera="obrotowa",
        plate=None,
    ):
        record = SimpleNamespace(id=eid, label="car")
        obs = VehicleObservation(
            event_id=eid,
            camera=camera,
            start_time=at,
            end_time=at + 4,
            box=self.BOX if box is None else box,
            image_hash=digest,
            license_plate=plate,
        )
        return record, obs

    def record(self, entry):
        event, obs = entry
        with patch("frigate.vehicle_visits.store.inspect_event", return_value=obs):
            return link_event_to_visit(event)

    def test_first_event_creates_persistent_visit_and_mapping(self):
        self.assertEqual(self.record(self.event("a", 100)), ("a", "first_detection"))
        self.assertEqual(VehicleVisit.select().count(), 1)
        self.assertEqual(VehicleVisitEvent.get_by_id("a").visit_id, "a")

    def test_new_visit_with_frigate_queued_database(self):
        """Queue-backed SQLite cannot use get_or_create() or atomic()."""
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "visits.db")
            schema_db = SqliteExtDatabase(path)
            schema_db.bind([VehicleVisit, VehicleVisitEvent])
            schema_db.connect()
            schema_db.create_tables([VehicleVisit, VehicleVisitEvent])
            schema_db.close()

            queued_db = SqliteVecQueueDatabase(path, load_vec_extension=False)
            queued_db.bind([VehicleVisit, VehicleVisitEvent])
            try:
                # Missing thumbnail still must produce the first visit.
                first = self.event("queued-a", 100, digest=None)
                self.assertEqual(self.record(first), ("queued-a", "first_detection"))
                self.assertEqual(
                    VehicleVisitEvent.get_by_id("queued-a").visit_id,
                    "queued-a",
                )
                self.assertEqual(VehicleVisit.select().count(), 1)
                # Replaying the same event must not duplicate its link.
                self.assertEqual(self.record(first)[0], "queued-a")
                self.assertEqual(VehicleVisitEvent.select().count(), 1)
            finally:
                queued_db.stop()
                self.db.bind([VehicleVisit, VehicleVisitEvent])

    def test_repeat_same_event_does_not_create_second_visit(self):
        self.record(self.event("a", 100))
        self.record(self.event("a", 100))
        self.assertEqual(VehicleVisit.select().count(), 1)
        self.assertEqual(VehicleVisitEvent.select().count(), 1)

    def test_same_parked_car_new_id_joins_first_visit(self):
        self.record(self.event("a", 100))
        self.assertEqual(self.record(self.event("b", 3700))[0], "a")
        self.assertEqual(VehicleVisit.select().count(), 1)
        self.assertEqual(VehicleVisitEvent.select().count(), 2)

    def test_second_car_at_other_position_stays_separate(self):
        self.record(self.event("a", 100))
        self.assertEqual(
            self.record(self.event("b", 110, box=(0.72, 0.2, 0.95, 0.7)))[0], "b"
        )
        self.assertEqual(VehicleVisit.select().count(), 2)

    def test_different_plate_never_joins(self):
        self.record(self.event("a", 100, plate="KR11111"))
        self.assertEqual(self.record(self.event("b", 110, plate="KR22222"))[0], "b")

    def test_new_view_of_same_track_is_retained_for_later_matches(self):
        self.record(self.event("a", 100, digest=0x33CC001122334455))
        self.record(
            self.event("a", 100, digest=0xAA55110022334455, box=(0.4, 0.1, 0.8, 0.6))
        )
        self.assertEqual(
            self.record(
                self.event(
                    "b", 200, digest=0xAA55110022334455, box=(0.4, 0.1, 0.8, 0.6)
                )
            )[0],
            "a",
        )
        self.assertEqual(VehicleVisit.select().count(), 1)

    def test_missing_image_does_not_implicitly_join(self):
        self.record(self.event("a", 100, digest=None))
        self.assertEqual(self.record(self.event("b", 105, digest=None))[0], "b")

    def test_ambiguous_candidate_keeps_new_visit(self):
        # A and B differ by six bits (not a match), while C is within
        # three bits of both, so no single visit may be selected.
        self.record(self.event("a", 100, digest=0x33CC001122334400))
        self.record(self.event("b", 110, digest=0x33CC00112233443F))
        self.assertEqual(
            self.record(self.event("c", 120, digest=0x33CC001122334407)),
            ("c", "ambiguous_match"),
        )

    def test_twelve_hour_gap_starts_new_visit(self):
        self.record(self.event("a", 100))
        self.assertEqual(self.record(self.event("b", 100 + 12 * 3600 + 50))[0], "b")

    def stored_event(self, eid, at, camera="obrotowa"):
        return Event.create(
            id=eid,
            camera=camera,
            label="car",
            start_time=at,
            end_time=at + 4,
            top_score=0.9,
            score=0.9,
            false_positive=False,
            zones=[],
            thumbnail="",
            region=[],
            box=[],
            area=0,
            plus_id="",
            model_hash="",
            detector_type="",
            model_type="",
            data={},
        )

    def test_manual_merge_split_and_close_on_queued_database(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "manual.db")
            models = [Event, VehicleVisit, VehicleVisitEvent]
            schema = SqliteExtDatabase(path)
            schema.bind(models)
            schema.connect()
            schema.create_tables(models)
            schema.close()
            queued = SqliteVecQueueDatabase(path, load_vec_extension=False)
            queued.bind(models)
            try:
                a = self.stored_event("a", 100)
                b = self.stored_event("b", 200)
                observations = {
                    "a": self.event("a", 100)[1],
                    "b": self.event("b", 200, digest=0xAA55110022334455)[1],
                }
                with patch(
                    "frigate.vehicle_visits.store.inspect_event",
                    side_effect=lambda event: observations[event.id],
                ):
                    link_event_to_visit(a)
                    link_event_to_visit(b)
                    joined = correct_vehicle_events([a, b], "merge")
                    self.assertEqual(
                        VehicleVisitEvent.get_by_id("a").visit_id, joined
                    )
                    self.assertEqual(
                        VehicleVisitEvent.get_by_id("b").visit_id, joined
                    )
                    self.assertIsNone(VehicleVisit.get_by_id(joined).closed_at)
                    separated = correct_vehicle_events([b], "split")
                    self.assertNotEqual(separated, joined)
                    self.assertEqual(
                        VehicleVisitEvent.get_by_id("a").visit_id, joined
                    )
                    self.assertEqual(
                        VehicleVisitEvent.get_by_id("b").visit_id, separated
                    )
                    self.assertEqual(correct_vehicle_events([a], "close"), joined)
                    self.assertIsNotNone(VehicleVisit.get_by_id(joined).closed_at)
                    self.assertEqual(link_event_to_visit(b)[0], separated)
                    self.assertEqual(Event.select().count(), 2)
                self.assertEqual(self.record(self.event("c", 300))[0], "c")
            finally:
                queued.stop()
                self.db.bind(models)

    def test_historical_read_groups_only_visible_camera(self):
        from frigate.api.vehicle_visits import VehicleGroupRequest, groups_for_events

        self.stored_event("a", 100)
        self.stored_event("b", 200)
        self.stored_event("c", 300, camera="other")
        observations = {
            "a": self.event("a", 100)[1],
            "b": self.event("b", 200)[1],
        }
        with patch(
            "frigate.api.vehicle_visits.inspect_event",
            side_effect=lambda event: observations[event.id],
        ):
            groups = groups_for_events(
                VehicleGroupRequest(event_ids=["a", "b", "c"]),
                ["obrotowa"],
            )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["event_ids"], ["a", "b"])
        self.assertEqual(VehicleVisitEvent.select().count(), 0)

    def test_confirmed_departure_prevents_rejoining(self):
        self.record(self.event("a", 100))
        VehicleVisit.update(closed_at=104).where(VehicleVisit.id == "a").execute()
        self.assertEqual(self.record(self.event("b", 120))[0], "b")

    def test_mapping_survives_reinitializing_service(self):
        self.record(self.event("a", 100))
        # A new call resolves the persisted mapping from the database only.
        self.assertEqual(self.record(self.event("a", 100))[0], "a")


if __name__ == "__main__":
    unittest.main()
