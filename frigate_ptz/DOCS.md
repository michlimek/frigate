# SimplyQ Frigate PTZ

The app uses a prebuilt image from `ghcr.io/michlimek/frigate`.
No Docker compilation happens on the Home Assistant host.

If you have the old `local_frigate-ptz` app, do not start this app before
copying over the original Frigate configuration and database. The app ID
changes when migrating from a local source to this GitHub repository.

Backup the original add-on configuration and all Frigate data before
migrating. Start the new app only after successful data migration. In
particular, never run two Frigate instances recording the same cameras to
the same media at once.

Updates appear here **only after a prebuilt external image is verified and
promoted**. Leave automatic app updates disabled.
