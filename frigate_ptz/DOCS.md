# Frigate PTZ Fix for Home Assistant, 0.18.2.post1

This add-on **does not require GitHub Actions or a GHCR image** from the
SimplyQ fork. Home Assistant Supervisor builds the image locally when
installing or updating this source-based add-on.

The multi-stage Dockerfile checks out a **pinned commit** of
`michlimek/frigate` from `release/0.18.2`, compiles the web UI using
Node 20, then overlays Python code, migrations, and frontend onto the
official Frigate 0.18.2 runtime image. It does not modify files in the
running Frigate container.

## Existing local installation (preferred for Słopnice3)

If the current add-on has identity `local_frigate-ptz`, **do not**
install the GitHub repository version alongside it. The repository source
prefix would be different and HA would create a second add-on.

Instead:
1. Create a complete HA backup. Back up the Frigate add-on `/config`
   directory, especially `frigate.db`, and record the previous image tag.
2. Keep the exact existing `/addons/frigate_ptz/config.yaml` (or your actual
   local add-on directory) with all custom devices, volumes, and ports.
3. Add the `Dockerfile` from this folder to that same local add-on folder.
4. Change its `version` to `"0.18.2.post1"` and **delete its `image:`
   line**. Keep `slug: frigate-ptz` and every other existing field.
   The included `upgrade-local.sh` performs only these two manifest edits,
   after backing up `config.yaml`. Run it from the add-on directory.
5. In Home Assistant: Settings > Add-ons/Apps > Add-on Store, reload,
   open **Frigate 0.18.2 PTZ Fix**, then update.
6. Supervisor downloads source from GitHub during the local Docker build.
   This is CPU/RAM/disk-intensive (Node build) and can take significant time.
7. Verify that the Frigate API, PTZ and the Vehicle visits page work before
   enabling `frigate_vehicle_visits: true` in Driveway Guard.

## Fresh install with GitHub repository

Add repository URL:
`https://github.com/michlimek/frigate#release/0.18.2`

Open **Frigate 0.18.2 PTZ Fix** and Install. The new add-on will have a
different repository-prefixed identity from an existing `local_frigate-ptz`.
Running both Frigate instances simultaneously is not recommended. Existing
`/addon_configs/local_frigate-ptz/` files will not be automatically carried
over to a new installation.

When a newer version is committed to this GitHub add-on manifest, the
Supervisor can detect it after reloading the repository. A version change is
required for an update to appear; the Docker build does not perform
continuous git polling.

## Notes

- Source pinned to commit `7f79b8b31742b51b36380e47c1485480a9d9c9c3`.
- Runtime base: `ghcr.io/blakeblackshear/frigate:0.18.2`.
- AMD64 only for this test add-on.
- No image tag in `config.yaml`: local Supervisor build is used.
- The database migration cannot be automatically reversed when reverting
  the container, so save the database backup.
- Complete Docker build and real camera regression tests were not run by
  ChatGPT. Do not assume success until Supervisor's build finishes.
