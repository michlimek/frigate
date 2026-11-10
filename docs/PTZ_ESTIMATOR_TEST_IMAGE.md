# Frigate PTZ estimator: test image (AMD64)

This fork carries a narrow fix to the PTZ movement-time regression in
`frigate/ptz/autotrack.py`. The regression was trained on
`[1.0, abs(pan) + abs(tilt)]` but used
`[saved_calibration_baseline, abs(pan) + abs(tilt)]` for prediction.
The corrected predictor uses the same feature vector as training.
Existing `movement_weights` remain compatible, with no recalibration.

## Build and publish

The fork provides `.github/workflows/ptz-estimator-test-image.yml`.
In the fork's GitHub **Actions** tab, enable fork workflows if prompted.
Select **PTZ Estimator Test Image (AMD64)**, choose the **dev** branch,
then **Run workflow**. A push to dev of the modified PTZ code or this
workflow also triggers the workflow when Actions are enabled.

The workflow builds from this fork's source using Frigate's actual
`docker/main/Dockerfile` with target `frigate`. Before publishing it
runs the PTZ regression tests in the resulting container and boots the
API with no cameras. Any failing step prevents publishing.

The two tags are:

```text
ghcr.io/michlimek/frigate:ptz-estimator-test-amd64
ghcr.io/michlimek/frigate:ptz-estimator-<FULL_COMMIT_SHA>-amd64
```

Prefer the immutable commit-specific tag for a controlled deployment.
An image is **not available** merely because this workflow file exists.
Check the Actions run is green and the GitHub Packages page lists the tag.
The first GHCR package may be private until you explicitly make it public;
log in with a read:packages token if Docker cannot pull it anonymously.

## Safe test on one camera

Only one Frigate instance should control a particular ONVIF PTZ camera.
Do **not** start a second autotracking Frigate on the same camera or mount
the same writable Frigate database/configuration into both instances.

For a Docker/Compose installation:

1. Back up `/config` (especially `config.yml`, `frigate.db`,
   credentials and TLS keys), and retain the existing image tag/digest.
   Record the old compose file and make sure recordings storage is safe.
2. Pull the fork's commit-tagged AMD64 image while the original instance
   is still running. Confirm that the tag resolves and the build succeeded.
3. Stop the existing Frigate and change **only** its Docker Compose
   `image:` reference to the test tag. Keep the same volume mappings,
   networks, device access, detector and camera settings.
4. Start a single Frigate instance. Check camera detections, go2rtc,
   ONVIF and PTZ tracking. Compare `Predicted movement time` versus
   `Actual movement time` across multiple real movements.
5. Roll back by stopping Frigate, restoring the original `image:`
   reference and restarting. Restore the backed-up config/database only
   if a schema or configuration change occurred.

For a **Home Assistant-managed Frigate add-on**, simply changing an
image name in Docker Compose does not apply. Use a supported local add-on
variant built from this fork or test on a dedicated Docker host; do not
modify Supervisor-managed add-on containers behind Supervisor's back.

This is a testing image for the selected fork's `dev` branch, not a
production or upstream Frigate release. The PTZ-time change has no
hardware-validated latency improvement yet, and its purpose is better
prediction, **not faster physical motors**.
