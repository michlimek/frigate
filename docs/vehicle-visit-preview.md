# PTZ vehicle visits

Vehicle visits group multiple Frigate `car` tracking events into one logical
visit. Each event retains its original ID, thumbnail, clip and recording
segments. No MP4 concatenation or deletion takes place.

## How it works

- For cameras configured with PTZ autotracking for `car`, Frigate writes
  an entry into `vehiclevisitevent` while storing each real `car` event. The
  corresponding `vehiclevisit` row is durable across Frigate restarts.
  Other cameras are not automatically grouped, but their retained car events
  can be imported explicitly through the admin backfill endpoint.
- A visit ID is the first Frigate event ID in the group.
- Strong picture similarity (grayscale dHash) **and** strong relative box
  overlap are required to connect different event IDs.
- Several camera viewpoints can be remembered if they were captured under
  the **same Frigate tracking ID**, which is stronger continuity evidence.
- Different camera IDs or conflicting recognized number plates cannot match.
- Ambiguous matching creates a separate visit rather than hiding a second car.
- Matching candidates are capped to the previous 12 hours. There is no
  time-only merge.
- The dedicated PTZ `car` Norfair tracker uses camera-motion-aware
  reidentification; static camera tracking is unchanged.

The algorithm intentionally remains conservative. Image hashes and box
coordinates are not reliable across completely different PTZ viewpoints. It
can fail to merge the same car when Frigate loses tracking during pan/zoom.
Conversely, an identical car returning to the same spot without a confirmed
departure can be matched to the earlier visit inside the 12-hour window.
For security-critical use, independent approach/absence evidence is needed.

## UI

Open **Vehicle visits** from the Frigate navigation. Visits are displayed as
one card per visit with one representative thumbnail and an ordered playlist
of all still-retained source clips. Each clip links to the normal Frigate
Review timeline. This is a separate view; the original Review timeline still
shows ordinary Frigate review segments.

Recordings are referenced, not rewritten. Source events and original review
records remain available and obey existing Frigate retention settings.

## API

All endpoints require authentication and are scoped to cameras the caller
can access.

- `GET /api/vehicle_visits?camera=obrotowa&hours=48&limit=100`: persisted
  visits with ordered source event IDs and playback information.
- `GET /api/vehicle_visits/lookup?camera=obrotowa&event_id=EVENT_ID`: resolve
  one event to `visit_id`; returns 404 until the event is persisted.
- `GET /api/vehicle_visits/preview?camera=obrotowa&hours=24&limit=200`:
  existing read-only historical preview; unlike the persisted list, does not
  change the database.

The two new tables are installed by migration
`036_create_vehicle_visit_tables.py`. Frigate's built-in migration process
creates a backup before applying database migrations. Take an independent
database backup before deploying a test build.

## Historical backfill

When this version is installed, new car events are linked automatically to
persistent visits. To import existing retained detections, open the Vehicle
visits page as an administrator and choose **Import history**. This explicitly
calls `POST /api/vehicle_visits/backfill?camera=obrotowa&hours=48&limit=250`
and processes at most 250 unlinked historical events in chronological order
per request. Repeat the import while the response indicates more history.

The import never deletes existing events or modifies recording files. Failed
events are reported, while valid events can still be imported. Previously
expired events or deleted thumbnails cannot be restored by the import.

## Driveway Guard

Version 0.3.3 can optionally resolve `visit_id` through the second endpoint.
Set `frigate_vehicle_visits: true` only after installing a Frigate build
containing this feature. Multiple re-detections already linked to one visit
then do not trigger new Driveway Guard notifications. A bounded six-second
wait handles database-save latency; if the API fails, Driveway Guard returns
to its earlier local matching rather than losing all arrival alerts.

The new feature does not change Frigate's native MQTT `frigate/events`
payload. Existing consumers remain compatible.

## Installable image: SimplyQ 0.18.2.post2

Frigate 0.18.2.post1 failed to build locally on Home Assistant Słopnice3.
Node/Vite reached the approximately 2 GiB V8 heap limit and aborted during
`npm run build`. This source-building add-on must not be retried.

The new **external-only** Dockerfile
`docker/ptz-vehicle-visits-release.Dockerfile` uses
`NODE_OPTIONS=--max-old-space-size=4096` on an external build machine,
copies the complete fork backend, migrations and compiled web UI onto the
official Frigate 0.18.2 runtime, and keeps the old PTZ fixes.

The new HA add-on has **no Dockerfile** and only pulls:

```yaml
slug: frigate-ptz
version: "0.18.2.post2"
image: ghcr.io/michlimek/frigate
```

The image reference used by HA Supervisor will be:
`ghcr.io/michlimek/frigate:0.18.2.post2`.

This image is **not available merely because the version was committed**.
External CI must pass the unit tests, compiled frontend check, Frigate API
startup and SQLite migration smoke test, publish the image to GHCR, and
ensure that it can be pulled without authentication before the add-on is
upgraded. No image should be published when tests fail.

### Existing local HA add-on: `local_frigate-ptz`

Keep the exact current add-on slug and installation; do not install a
second Frigate. To undo the failed 0.18.2.post1 attempt, use
`frigate_ptz/restore-local-stable.sh` in the **existing local add-on
folder** (with the original `config.yaml.bak-before-0.18.2.post1`).
This safely restores the old prebuilt image configuration, preserving a
copy of the failed manifest.

When (and only when) GHCR reports the new image is publicly pullable,
copy `frigate_ptz/upgrade-local-prebuilt.sh` to that same folder and run
it. The script validates anonymous access to the exact GHCR manifest,
preserves the existing slug, maps, devices, ports and user settings, creates
a backup, then updates only `version` and `image`. It refuses to
change files if the image is missing. Refresh the local add-ons store,
then update the existing add-on.

The old `frigate_ptz/upgrade-local.sh` which removes the `image` field
and triggers local Docker compilation must never be used again.

### External build without GitHub Actions

On an AMD64 Linux workstation or an x86-64 PC running Docker Desktop/WSL2
and Git, check out the post2 candidate (before merge) or release source
(after merge) and run
`testing-scripts/release-frigate-prebuilt-amd64.sh`. It tests locally and
does not publish by default. When validated and authenticated to GHCR,
re-run with `PUBLISH=1` to publish.

Before the first start of this new version, independently back up
`/config/frigate.db`, Frigate configuration and recordings. An image
rollback cannot reverse a completed SQLite migration.

Keep Driveway Guard `frigate_vehicle_visits` **disabled** until the
camera PTZ behavior and separate arrivals have been validated on the
installed version.

## Validation

Run the repository checks in a Frigate development environment:

```sh
python3 -u -m unittest frigate.test.test_vehicle_visit_matching
python3 -u -m unittest frigate.test.test_vehicle_visit_store
python3 generate_api_auth_spec.py
python3 generate_api_auth_spec.py --check
ruff check frigate/vehicle_visits frigate/api/vehicle_visits.py
ruff format --check frigate/vehicle_visits frigate/api/vehicle_visits.py
npm --prefix web run lint
npm --prefix web run build
```

The OpenAPI generator must be run from a fully installed Frigate checkout
because its imports need the complete application dependencies. Do not edit
`docs/static/frigate-api.yaml` manually.

Before production promotion, replay representative actual PTZ events:
stationary car reacquired after camera pan, a second similar car arriving,
a car entering the garage, the same car leaving and returning, and camera
restarts. No confidence metric can make an ambiguous single-frame match
infallible.
