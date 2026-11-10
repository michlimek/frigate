# PTZ movement-time regression: isolated AMD64 test image

This personal fork has a minimal change in `frigate/ptz/autotrack.py`:
the predictor must use the same feature vector as linear regression training.
No live PTZ movement commands, ONVIF bridge, MQTT topics, calibration format
or user configuration format have been changed.

## Building a test image in GitHub Actions

1. Open the **Actions** tab in `michlimek/frigate`. If fork workflows are
   disabled, enable them using GitHub's **I understand my workflows** control.
2. Select **PTZ Test Image (AMD64)** and **Run workflow**, branch `dev`.
3. Check that the entire job including the isolated API smoke test is green.
4. Use the immutable tag printed in the job summary:
   `ghcr.io/michlimek/frigate:ptz-time-<seven-character-commit>-amd64`.
   The workflow publishes **linux/amd64 only**. Do not assume the tag exists
   until the workflow has successfully published it.

The build uses the normal `docker/main/Dockerfile` and the upstream
`frigate` target, not a thin Python-only overlay.

## Deployment safety

This fork tracks Frigate **dev**, which may differ in more than the PTZ fix
from the currently installed upstream **stable** release. The dev image may
migrate the configuration or SQLite database. An image rollback without
restoring those files is not guaranteed to work.

- First test the image in a separate, disposable container with a fresh,
  isolated `/config`, separate ports and **no cameras, MQTT or autotracking**.
  The GitHub Actions smoke test does this automatically.
- For a real PTZ A/B test, preserve a copy of the original `/config`
  (including `frigate.db`) and the exact original image tag/digest. Stop
  the original Frigate before starting the test image with that camera.
  Use a copied configuration/database for a reversible test when possible.
- Never run two active Frigate autotrackers simultaneously against the same
  camera. Do not mount the same writable `/config` or SQLite DB into two
  containers. Use the same detector/stream settings only during controlled
  single-instance comparison.
- If Frigate is installed as a Home Assistant add-on rather than an
  independent Docker/Proxmox container, do not paste the GHCR tag into
  Supervisor add-on settings. A custom add-on image/manifest or different
  installation method is required.
- On rollback, stop the test container and restore the original
  image **and** the backed-up configuration/database when migrated.

## What to compare

Enable PTZ debug logging for the test camera and capture paired
`Predicted movement time` and `Actual movement time` entries for the
same moves before and after deployment. Record the exact tested image tag.

This change corrects the prediction formula but does **not** accelerate
physical Pan/Tilt motors or guarantee faster reacquisition. Hardware
validation and full project CI remain distinct from the isolated API
smoke test.
