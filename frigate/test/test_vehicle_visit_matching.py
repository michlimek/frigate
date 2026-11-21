"""Regression tests for conservative vehicle event grouping."""

import unittest

from frigate.vehicle_visits.matching import (
    VehicleObservation,
    group_vehicle_events,
    image_distance,
    intersection_over_union,
)


class TestVehicleVisitMatching(unittest.TestCase):
    BOX = (0.30, 0.20, 0.70, 0.80)

    def event(self, name, time, box=None, image_hash=None, camera="obrotowa", plate=None):
        return VehicleObservation(
            name, camera, time, time + 4,
            self.BOX if box is None else box,
            0x55AA12F07A71B1AA if image_hash is None else image_hash,
            plate,
        )

    def test_same_parked_car_after_camera_returns(self):
        visits = group_vehicle_events([self.event("a", 100), self.event("b", 3700)])
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0].events, ["a", "b"])
        self.assertEqual(visits[0].matches[1], "stationary_visual_match")

    def test_second_car_in_different_area_is_not_merged(self):
        visits = group_vehicle_events([
            self.event("a", 100),
            self.event("b", 110, box=(0.71, 0.20, 0.96, 0.8)),
        ])
        self.assertEqual(len(visits), 2)

    def test_same_position_visually_different_car_is_not_merged(self):
        visits = group_vehicle_events([
            self.event("a", 100), self.event("b", 110, image_hash=0xAA55ED0F858E4E55),
        ])
        self.assertEqual(len(visits), 2)

    def test_different_plate_prevents_merge(self):
        visits = group_vehicle_events([
            self.event("a", 100, plate="KR12345"),
            self.event("b", 120, plate="KR12346"),
        ])
        self.assertEqual(len(visits), 2)

    def test_same_plate_without_images_does_not_merge(self):
        a = self.event("a", 100, plate="KR12345")
        b = self.event("b", 120, plate="KR12345")
        from dataclasses import replace
        visits = group_vehicle_events([replace(a, image_hash=None), replace(b, image_hash=None)])
        self.assertEqual(len(visits), 2)

    def test_events_from_different_cameras_do_not_merge(self):
        visits = group_vehicle_events([
            self.event("a", 100), self.event("b", 110, camera="other"),
        ])
        self.assertEqual(len(visits), 2)

    def test_different_visit_after_twelve_hours(self):
        visits = group_vehicle_events([
            self.event("a", 100), self.event("b", 100 + 12 * 3600 + 10),
        ])
        self.assertEqual(len(visits), 2)

    def test_duplicate_event_id_is_not_repeated(self):
        visits = group_vehicle_events([self.event("a", 100), self.event("a", 101)])
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0].events, ["a"])

    def test_appearance_anchor_does_not_drift_across_events(self):
        base = 0x55AA12F07A71B1AA
        visits = group_vehicle_events([
            self.event("a", 100, image_hash=base),
            self.event("b", 200, image_hash=base ^ 0x3),
            self.event("c", 1000, image_hash=base ^ 0xF),
        ])
        self.assertEqual(len(visits), 2)
        self.assertEqual(visits[0].events, ["a", "b"])

    def test_invalid_boxes_are_not_matched(self):
        self.assertEqual(intersection_over_union((0, 0, 0, 0), self.BOX), 0.0)
        self.assertEqual(intersection_over_union((0, 0, float('nan'), 1), self.BOX), 0.0)

    def test_invalid_image_hash_is_not_matched(self):
        self.assertIsNone(image_distance(-1, 2))
        self.assertIsNone(image_distance(1 << 65, 2))


if __name__ == "__main__":
    unittest.main()
