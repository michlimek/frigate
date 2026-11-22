# SimplyQ Frigate PTZ: Home Assistant app channel

This lightweight **ha-addon** branch is a Home Assistant repository. It
contains **only app metadata**, not Frigate source code or Dockerfiles.

Add this repository to Home Assistant using the URL:

```
https://github.com/michlimek/frigate#ha-addon
```

The first listed version uses the previously deployed PTZ image and makes
no changes to Frigate. The image name is
`ghcr.io/michlimek/frigate` and its tag always equals `version`.

**No Home Assistant build is ever required.** The actual Frigate backend,
migrations, and React frontend are built and tested on an external GitHub
runner. Only after the new image is pushed and anonymously pullable does
CI update `frigate_ptz/config.yaml` here. On the next store refresh HA
shows the update with a normal Update button.

## Important for existing Słopnice3 installation

The current app is `local_frigate-ptz`. The app installed from this
repository receives a **different repository prefix**, even though its
`slug` remains `frigate-ptz`. A one-time migration of `/config` data
is therefore required. Do NOT run both instances at once and do not
assume the Supervisor transfers the database automatically.

Perform a full backup of `/addon_configs/local_frigate-ptz`,
`frigate.db`, and recordings before switching. Stop the old app first.
Install the new app but do not start it until data have been copied from
the old app config directory to the new app config directory.

## Release controls

- No source archive, Dockerfile, npm or Vite build is contained in this
  branch.
- Only tested, published GHCR tags may be advertised as versions.
- No automatic installation on HA. Use manual Update.
- Keep an immutable image SHA digest in the release notes for rollback.
- The `ha-addon` branch must only be updated by release promotion after
  an anonymous GHCR manifest verification. Never bump `version` first.

Initial channel version: `ptz-0.18.2-3fe5164247bbe89187db248ba179ea999f700d83-amd64`.
