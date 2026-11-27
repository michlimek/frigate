# Frigate PTZ Fix - safe prebuilt-image release

Version: **0.18.2.post5** (AMD64).

This release deduplicates native MQTT car notifications on PTZ cameras, using the existing vehicle grouping algorithm. No new MQTT topics or Home Assistant blueprint are required. Native Review and Explore recordings remain intact.

## Existing GitHub add-on

Keep `https://github.com/michlimek/frigate#ha-addon` and update the existing
`frigate-ptz` add-on through the HA store after verified promotion. Do not add
the release source branch as a second repository. Back up `frigate.db` before upgrading. Post5 introduces no database migration. The release runner publishes the prebuilt image and
only then updates the existing stable channel after an anonymous pull check.

## Why local source building is disabled

The previous 0.18.2.post1 add-on had a multi-stage Dockerfile that ran
`npm run build` **inside Home Assistant Supervisor**. On Słopnice3 the build
failed at about 2 GiB of Node/V8 heap (`Allocation failed - JavaScript heap
out of memory`) and made the HA host temporarily unresponsive.

The new add-on definition has **no local Dockerfile** and uses:

```yaml
slug: frigate-ptz
version: "0.18.2.post5"
image: ghcr.io/michlimek/frigate
```

Home Assistant only pulls an **already built** image with exact tag
`ghcr.io/michlimek/frigate:0.18.2.post5`. The image must exist and be
anonymously pullable in GHCR. A GitHub commit or version bump alone does not
publish that image.

## Build and publish on an external computer / CI

For the initial pre-merge test use candidate branch
`feature/deduplicate-vehicle-mqtt`; after promotion use
`release/0.18.2`. Build with
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

**Upgrade when 0.18.2.post5 image is actually published:**

1. Verify the external CI/build and that GHCR image is public.
2. Copy `upgrade-local-prebuilt.sh` to your **existing** local add-on folder.
3. Run it from that folder. It will refuse to change the manifest unless it
   successfully downloads an anonymous pull token and resolves the exact
   `0.18.2.post5` manifest (HTTP 200).
4. Reload the local add-on store, update the existing PTZ Fix add-on, and
   verify live cameras, storage, PTZ, and grouped Review and Explore.
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

## Optional required NFS media storage

For an HA installation that must never intentionally fall back to local
media storage, create a plain text file named `required_storage_source`
in the app's local configuration directory (mapped to `/config`), containing
the exact NFS server and exported path as seen in the mount table, for
example:

```text
192.0.2.1:/mnt/pool/frigate
```

Restart the app to enable or change the requirement. Leave the file absent
to retain the normal Frigate behavior. A present but invalid file prevents
startup. Do not put the database on the NFS share.

The guard resolves the actual kernel mount ID of `/media/frigate`, rather
than guessing from a matching directory name or the autofs entry. Before
starting Frigate, it waits for the configured writable NFS source and
successfully creates, flushes and removes a unique probe file through the
verified directory descriptor. During operation it checks the actual
mount identity and read-only flags every five seconds. If the mount is
lost or replaced it requests shutdown of the complete Frigate container.
Enable the Home Assistant app Watchdog if automatic restart after failure
is desired; a manual start will also run the same startup check.

This is a periodic protection, not an atomic filesystem write barrier.
There is a short detection and shutdown window. An NFS server that is
unreachable while its mount remains attached does not trigger a mount-loss
shutdown merely because of connectivity loss; I/O may fail or block.
Monitor write health separately. A stopped app or a startup wait means
recordings, detection and live view are unavailable. Validate on the actual
HAOS host after release by checking startup with working NFS, deliberately
testing an unavailable share during a maintenance window, and checking
recovery before relying on the guard.
