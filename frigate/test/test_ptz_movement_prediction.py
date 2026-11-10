"""Regression tests for calibrated ONVIF PTZ movement time prediction."""

import unittest

import numpy as np

from frigate.ptz.autotrack import PtzAutoTracker


class TestCalibratedMovementPrediction(unittest.TestCase):
    """Predictions must use the same features as calibration regression."""

    def setUp(self) -> None:
        # Avoid the actual tracker startup, ONVIF connection and motors.
        self.tracker = PtzAutoTracker.__new__(PtzAutoTracker)
        self.camera = "ptz_cam"
        self.tracker.intercept = {self.camera: 0.25}
        self.tracker.move_coefficients = {
            self.camera: np.array([0.45, 0.85]),
        }

    def test_fitted_bias_is_not_scaled_by_calibration_baseline(self) -> None:
        self.assertAlmostEqual(
            self.tracker._predict_movement_time(self.camera, 0.3, -0.5),
            0.45 + 0.85 * (0.3 + 0.5),
        )

    def test_zero_motion_uses_the_regression_intercept(self) -> None:
        self.assertAlmostEqual(
            self.tracker._predict_movement_time(self.camera, 0, 0), 0.45
        )

    def test_saved_calibration_baseline_does_not_change_prediction(self) -> None:
        result = self.tracker._predict_movement_time(self.camera, 0.4, 0.2)
        self.tracker.intercept[self.camera] = 0.8
        self.assertAlmostEqual(
            self.tracker._predict_movement_time(self.camera, 0.4, 0.2),
            result,
        )

    def test_sum_of_axis_distances_is_retained(self) -> None:
        # This also covers hardware that executes Pan before Tilt.
        self.assertAlmostEqual(
            self.tracker._predict_movement_time(self.camera, 0.4, 0.3),
            0.45 + 0.85 * 0.7,
        )

    def test_matches_original_calibration_regression_features(self) -> None:
        movement = np.array([0.0, 0.4, 0.8, 1.2])
        duration = 0.5 + 1.1 * movement
        design = np.column_stack((np.ones(movement.shape[0]), movement))
        coefficients = np.linalg.lstsq(design, duration, rcond=None)[0]
        self.tracker.move_coefficients[self.camera] = coefficients
        self.tracker.intercept[self.camera] = float(duration[0])
        self.assertAlmostEqual(
            self.tracker._predict_movement_time(self.camera, 0.3, 0.5),
            0.5 + 1.1 * 0.8,
        )


if __name__ == "__main__":
    unittest.main()
