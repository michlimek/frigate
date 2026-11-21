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

## Installable image (SimplyQ 0.18.2.post1)

This repository has a dedicated AMD64 image build workflow for the full
Frigate backend, migrations and web frontend (not the older PTZ-only
overlay). It is built from `docker/main/Dockerfile`, and is pushed to
GHCR **only after** the container tests and API smoke test pass.

Image after a successful publish:

```yaml
image: ghcr.io/michlimek/frigate:0.18.2.post1-amd64
```

An immutable tag `0.18.2.post1-<commit-sha7>-amd64` is published in
addition to the version tag. Check the GitHub Actions workflow run and
GHCR package before pulling: a code merge alone does not publish an
image. The old `ptz-0.18.2-test-amd64` image **does not contain**
vehicle-visit code or frontend, because its Dockerfile copies only
`frigate/ptz/autotrack.py`.

### Home Assistant add-on upgrade

Home Assistant Supervisor pulls the `image` setting with the exact
`version` as the Docker image tag. For add-on installations, this release
therefore also publishes `ghcr.io/michlimek/frigate:0.18.2.post1`.

The add-on's original `config.yaml` needs this change in the **source
manifest**, not the add-on Options tab:

```yaml
version: "0.18.2.post1"
image: ghcr.io/michlimek/frigate
```

**Retain the existing `slug`, mounts, hardware permissions, network ports,
ingress and settings** for an in-place upgrade. Changing the add-on slug or
repository identifier makes Home Assistant treat it as a different add-on,
which requires migrating `config.yml` and other add-on-scoped data.
For official `ccab4aaf_frigate`, a third-party manifest cannot silently
replace the upstream add-on, which is owned by the Frigate add-ons
repository. The custom "Frigate 0.18.2 PTZ Fix" add-on should be updated in
its own add-on source repository or locally in `addons/local` if it is a
local add-on. Refresh the Add-on Store after updating its manifest.

The image must be published and publicly pullable *before* refreshing or
upgrading in Home Assistant. Do not attempt this in-place upgrade until the
GitHub Actions publishing run succeeds, and back up the add-on configuration
and database first.

Before replacing a running Frigate instance, back up its `/config`
directory (especially `frigate.db`) and record your current image tag.
Version 0.18.2.post1 adds a SQLite migration; switching the container
image back to a prior version does not reverse a completed database
migration. Do not enable Driveway Guard visit-ID suppression until
your real PTZ events have been checked for incorrect visit grouping.

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
