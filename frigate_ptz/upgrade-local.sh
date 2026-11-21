#!/bin/sh
# Safe update of the existing local_frigate-ptz add-on manifest.
set -eu
addon_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
config="$addon_dir/config.yaml"
if [ ! -f "$config" ]; then
  echo "No config.yaml found in $addon_dir; aborting." >&2
  exit 1
fi
if [ ! -f "$addon_dir/Dockerfile" ]; then
  echo "Dockerfile missing; aborting." >&2
  exit 1
fi
slug="$(awk '/^slug:/{print $2}' "$config" | tr -d '"' | tr -d "'")"
if [ "$slug" != "frigate-ptz" ]; then
  echo "Expected existing slug frigate-ptz; refusing to edit another add-on." >&2
  exit 1
fi
if ! grep -Eq '^version:[[:space:]]*' "$config"; then
  echo "No version found; refusing to edit manifest." >&2
  exit 1
fi
backup="$config.bak-before-0.18.2.post1"
if [ -e "$backup" ]; then
  echo "Backup already exists: $backup; refusing overwrite." >&2
  exit 1
fi
cp "$config" "$backup"
sed -e 's/^version:.*/version: "0.18.2.post1"/' -e '/^image:[[:space:]]*/d' "$backup" > "$config.new"
mv "$config.new" "$config"
echo "Manifest updated; preserved other add-on settings. Backup: $backup"
echo "Refresh Home Assistant local add-on store, then Update PTZ Fix."
