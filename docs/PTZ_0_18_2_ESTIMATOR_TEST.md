# Frigate 0.18.2: PTZ movement time estimator test

This fork branch `release/0.18.2` is based on upstream Frigate
`v0.18.2` (commit `cfa08c56b23d23280c3d0a218e5a43182c97445b`),
not the upstream 0.19 development branch.

## The patch

The existing regression estimator is fitted using
`[1.0, abs(pan) + abs(tilt)]`. Previously its prediction used
`[saved_calibration_baseline, abs(pan) + abs(tilt)]`, incorrectly
scaling the fitted constant. The patch corrects only the prediction
feature vector. It retains the camera's `movement_weights` format
and the PTZ control messages. No recalibration is needed.

Five unit tests cover the mismatch, zero displacement, changing saved
baseline, sequential Pan/Tilt distance and direct regression agreement.

## Test image (AMD64 only)

This branch includes
`.github/workflows/ptz-0.18.2-test-image.yml`, running on a push
to `release/0.18.2`, on PRs targeting the release branch,
and with a manual workflow trigger if GitHub Actions is enabled. The image is based on the official released
`ghcr.io/blakeblackshear/frigate:0.18.2`, with **only the 0.18.2
`frigate/ptz/autotrack.py` file overlaid**. This avoids building
historical third-party dependencies from retired download URLs.
The full Frigate 0.18.2 entrypoint, libraries, database format, detector
models and startup are preserved.

The workflow runs on PRs against `release/0.18.2` and after merging
on pushes to that branch. It executes five tests in the resulting
container using a read-only mounted test file and then checks the Frigate
API with an empty camera configuration. Only a successful push-branch
workflow publishes these fork-local GHCR tags:

```text
ghcr.io/michlimek/frigate:ptz-0.18.2-test-amd64
ghcr.io/michlimek/frigate:ptz-0.18.2-<FULL_SHA>-amd64
```

Use the commit-specific tag for deployment and rollback. An Actions
workflow existing does not mean an image is published. Verify the
successful run and the GHCR package tag before pulling it.

## Testing without disturbing the existing installation

Only one Frigate instance should control autotracking for a given
camera at any time. If testing alongside production, use separate
writable config/database/media volumes and turn off autotracking
for that same camera in the original Frigate.

If replacing an existing 0.18.2 Docker Compose container temporarily:
back up the configuration and database, record the original image
tag or digest, stop the original, change only the `image:` reference
to the fork's commit-pinned image, and restart. Roll back by restoring
the original image reference and restarting. Do not run two Frigate
instances against the same writable database.

For a Home Assistant Supervisor-managed Frigate add-on, the Docker
Compose procedure is not applicable. Use an appropriate local add-on
variant or a separate supported Docker host, rather than modifying
Supervisor-managed containers directly.

Capture logs for `Predicted movement time`, `Actual movement time`
and object tracking across real PTZ moves. This change is intended
to improve prediction fidelity, not make the physical motors faster.
