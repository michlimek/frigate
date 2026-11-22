# Frigate update channel for Home Assistant Słopnice3

Goal: after one-time migration, updates are a normal **Update** button in
Home Assistant. There is no npm, Node, Dockerfile or compilation on HA.

## Distribution repository

Home Assistant repository URL:

```
https://github.com/michlimek/frigate#ha-addon
```

The `ha-addon` branch deliberately contains only
`repository.yaml`, `README.md`, and `frigate_ptz/config.yaml` plus
user-facing documentation. Source code and Dockerfiles are not present.

Home Assistant identifies this as a separate repository from the current
local `local_frigate-ptz` app. The app slug stays `frigate-ptz`, but the
repository prefix changes. This **requires one-time data migration**, not
an in-place upgrade. Do not install two running Frigate instances.

The initial channel advertises exactly the previously installed PTZ build
`ptz-0.18.2-3fe5164247bbe89187db248ba179ea999f700d83-amd64`.
It must not advertise the unbuilt `0.18.2.post2` image.

## Automatic release flow

Default-branch GitHub Actions:
`.github/workflows/release-ha-addon.yml`

- At a scheduled interval, and via workflow_dispatch, select the highest
  unpublished source version (the `release/0.18.2` branch or the explicit
  `fix/ha-ptz-prebuilt-only-0.18.2.post2` candidate).
- Compare the source version with `ha-addon/frigate_ptz/config.yaml`.
  If the channel already advertises it, skip the build entirely.
- Verify that source app metadata references a prebuilt GHCR image and
  that the source add-on has **no Dockerfile**.
- Build complete backend, migrations and frontend outside HA on Ubuntu
  AMD64, with a larger Node heap.
- Run vehicle-visit and PTZ regression tests, inspect bundled assets,
  start Frigate in an isolated test container and validate its API and
  SQLite migration.
- Push the tested image to GHCR and verify it is **anonymously pullable**
  before modifying `ha-addon`.
- Update only `ha-addon/frigate_ptz/config.yaml` as the **last step**.
  HA sees the new version on its next store refresh. Automatic installation
  remains disabled.

An unavailable or private GHCR tag MUST NOT result in a visible HA update.
Failed compilation, unit tests, startup, migration, registry publication
or anonymous access aborts promotion.

The workflow depends on repository GitHub Actions being **enabled** and
a token with `packages:write` and `contents:write`. The integrated
GitHub connector cannot start workflow_dispatch, and recent repository
runs have not demonstrated that new workflows are executing. Verify a
successful run before making the initial migration.

## One-time migration from local_frigate-ptz

1. Confirm the release channel currently references a tested image.
   Make a full Home Assistant backup; preserve Frigate media and
   `frigate.db`.
2. Add the repository URL above in the HA App Store (Apps > three dots >
   Repositories). Use the **`#ha-addon`** suffix.
3. Stop the existing **Frigate 0.18.2 PTZ Fix** (`local_frigate-ptz`).
4. Install the new SimplyQ Frigate PTZ app but **do not start it**.
5. With Samba or an HA file manager that has access to all app configs,
   copy the contents of
   `/addon_configs/local_frigate-ptz/` to the new app's config directory,
   `/addon_configs/<repo-id>_frigate-ptz/`. The repository identifier is
   supplied by HA, not guessed from a URL. If the existing installation
   uses a different directory or a different volume layout, stop and
   inspect the actual mappings.
6. Verify that `config.yml`, any `frigate.db` and all custom files
   were copied. Do not delete originals.
7. Start the new app and verify the cameras, PTZ, recordings, and
   existing integrations. Update any HA endpoints that refer to the old
   app hostname. Only after validation decide whether to remove the
   stopped local app.
8. Leave auto-update disabled in HA; perform image updates by clicking
   **Update** after reviewing the release notes and taking a backup.

Modern Home Assistant may label these as `/app_configs`, rather than
`/addon_configs`; older names remain supported. The new repository ID
is a hash based on the repository URL including the branch suffix.

This migration has **not** been run on Słopnice3. The Home Assistant
connector is read-only; the assistant cannot copy the actual database or
start/stop apps. Avoid initiating migration until the release image and
CI are verified.

## Rollback

If the new app fails, stop it and restart the existing local app that was
left installed. Do not share a writable Frigate database between two
running instances. Note that a later Frigate version may migrate its own
new database copy; an image rollback alone cannot revert those migrations.

## Source of truth

Image repository: `ghcr.io/michlimek/frigate`.
Public HA channel: `ha-addon` branch.
Version is taken from source `Makefile` and source
`frigate_ptz/config.yaml` and compared before publishing.
The stable old PTZ build is used solely as the initial channel release.
