#!/bin/sh
# Restore original add-on image manifest after unsuccessful local build.
set -eu
addon_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
config="$addon_dir/config.yaml"
old="$addon_dir/config.yaml.bak-before-0.18.2.post1"
save="$addon_dir/config.yaml.bak-recovery-current"

if [ ! -f "$config" ] || [ ! -f "$old" ]; then
  echo "Current config or original pre-0.18.2.post1 backup is missing" >&2
  exit 1
fi
if [ -e "$save" ]; then
  echo "Refusing to overwrite existing backup: $save" >&2
  exit 1
fi
original_slug="$(awk '/^slug:/{print $2}' "$old" | tr -d '"' | tr -d "'")"
current_slug="$(awk '/^slug:/{print $2}' "$config" | tr -d '"' | tr -d "'")"
if [ "$original_slug" != "frigate-ptz" ] || [ "$current_slug" != "frigate-ptz" ]; then
  echo "Unexpected add-on slug; refusing to restore" >&2
  exit 1
fi
if ! grep -Eq '^image:[[:space:]]*' "$old"; then
  echo "Original manifest does not identify a prebuilt image; aborting" >&2
  exit 1
fi
cp "$config" "$save"
cp "$old" "$config"
echo "Restored original manifest. Current manifest preserved in $save"
echo "Reload add-ons in Home Assistant. Do not retry post1 source build."
