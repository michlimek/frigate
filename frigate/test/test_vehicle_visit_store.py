"""Persistent vehicle-visit mapping regressions."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from playhouse.sqlite_ext import SqliteExtDatabase

from frigate.models import VehicleVisit, VehicleVisitEvent
from frigate.vehicle_visits.matching import VehicleObservation
from frigate.vehicle_visits.store import link_event_to_visit


class TestVehicleVisitStore(unittest.TestCase):
    BOX = (0.2, 0.2, 0.7, 0.7)

    def setUp(self):
        self.db = SqliteExtDatabase(":memory:")
        self.db.bind([VehicleVisit, VehicleVisitEvent])
        self.db.connect()
        self.db.create_tables([VehicleVisit, VehicleVisitEvent])

    def tearDown(self):
        self.db.drop_tables([VehicleVisitEvent, VehicleVisit])
        self.db.close()

    def event(self, eid, at, digest=0x33CC001122334455, box=None, camera="obrotowa", plate=None):
        record = SimpleNamespace(id=eid, label="car")
        obs = VehicleObservation(
            event_id=eid, camera=camera, start_time=at, end_time=at + 4,
            box=self.BOX if box is None else box,
            image_hash=digest, license_plate=plate,
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
        self.assertEqual(self.record(self.event("b", 110, box=(0.72, 0.2, 0.95, 0.7)))[0], "b")
        self.assertEqual(VehicleVisit.select().count(), 2)

    def test_different_plate_never_joins(self):
        self.record(self.event("a", 100, plate="KR11111"))
        self.assertEqual(self.record(self.event("b", 110, plate="KR22222"))[0], "b")

    def test_new_view_of_same_track_is_retained_for_later_matches(self):
        self.record(self.event("a", 100, digest=0x33CC001122334455))
        self.record(self.event("a", 100, digest=0xAA55110022334455, box=(0.4, 0.1, 0.8, 0.6)))
        self.assertEqual(self.record(self.event(
            "b", 200, digest=0xAA55110022334455, box=(0.4, 0.1, 0.8, 0.6)
        ))[0], "a")
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
        self.assertEqual(self.record(self.event("b", 100 + 12*3600 + 50))[0], "b")

    def test_mapping_survives_reinitializing_service(self):
        self.record(self.event("a", 100))
        # A new call resolves the persisted mapping from the database only.
        self.assertEqual(self.record(self.event("a", 100))[0], "a")


if __name__ == "__main__":
    unittest.main()
