# Frigate PTZ Fix - safe prebuilt-image release

Version: **0.18.2.post2** (AMD64).

## Why local source building is disabled

The previous 0.18.2.post1 add-on had a multi-stage Dockerfile that ran
`npm run build` **inside Home Assistant Supervisor**. On Słopnice3 the build
failed at about 2 GiB of Node/V8 heap (`Allocation failed - JavaScript heap
out of memory`) and made the HA host temporarily unresponsive.

The new add-on definition has **no local Dockerfile** and uses:

```yaml
slug: frigate-ptz
version: "0.18.2.post2"
image: ghcr.io/michlimek/frigate
```

Home Assistant only pulls an **already built** image with exact tag
`ghcr.io/michlimek/frigate:0.18.2.post2`. The image must exist and be
anonymously pullable in GHCR. A GitHub commit or version bump alone does not
publish that image.

## Build and publish on an external computer / CI

Release source is `release/0.18.2`. Build with
`docker/ptz-vehicle-visits-release.Dockerfile` on an AMD64 host with enough
RAM, not on a Home Assistant device. The release workflow builds the web UI
with 4 GiB of Node/V8 heap, starts from the official Frigate 0.18.2 image,
overlays the complete fork backend, migrations and built frontend, runs
focused tests and smoke-tests startup **before** publishing the tag.

If GitHub Actions is unavailable, use Docker on an **external** computer,
run the same build and tests, then publish to GHCR using an account with
`write:packages` access. Never ask HA Supervisor to compile the frontend.

## Existing local add-on Słopnice3: `local_frigate-ptz`

**Immediate recovery** after failed post1 update (no image publication needed):

1. Stop retrying the 0.18.2.post1 update.
2. Back up HA and Frigate data (`frigate.db`, `config.yml`, recordings).
3. Copy `restore-local-stable.sh` to the existing local add-on folder
   (commonly `/addons/frigate_ptz`), and execute it there. This restores
   `config.yaml.bak-before-0.18.2.post1` and preserves the current manifest.
4. Reload the local add-on repository in the Home Assistant Store. Do not
   install a second Frigate instance.

**Upgrade when 0.18.2.post2 image is actually published:**

1. Verify the external CI/build and that GHCR image is public.
2. Copy `upgrade-local-prebuilt.sh` to your **existing** local add-on folder.
3. Run it from that folder. It will refuse to change the manifest unless it
   successfully downloads an anonymous pull token and resolves the exact
   `0.18.2.post2` manifest (HTTP 200).
4. Reload the local add-on store, update the existing PTZ Fix add-on, and
   verify live cameras, storage, PTZ, and vehicle-visits pages.
5. Keep Driveway Guard `frigate_vehicle_visits` disabled until actual
   camera recordings confirm that separate arrivals are not merged incorrectly.

Both scripts preserve `slug: frigate-ptz`. `upgrade-local-prebuilt.sh`
changes only `version` and `image` in the existing manifest. The old
source-building `upgrade-local.sh` must not be used again.

## Backups and rollback

The original camera config and recordings are not altered by these scripts.
However the **Frigate application** may migrate `frigate.db` when the
new image is first started. Back up `frigate.db` first. Rolling back an
image does not roll back a migrated database.

Do not create a second add-on from the GitHub repository on the production
host unless explicitly migrating the existing `local_frigate-ptz` identity.
