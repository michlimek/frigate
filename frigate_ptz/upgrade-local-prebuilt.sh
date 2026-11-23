#!/bin/sh
# In-place upgrade of the existing HA local_frigate-ptz add-on.
# Never build Frigate on the Home Assistant host.
set -eu
addon_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
config="$addon_dir/config.yaml"
version="0.18.2.post3"
registry="ghcr.io"
image="ghcr.io/michlimek/frigate"

if [ ! -f "$config" ]; then
  echo "No config.yaml found in $addon_dir" >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to verify the external prebuilt image" >&2
  exit 1
fi
slug="$(awk '/^slug:/{print $2}' "$config" | tr -d '"' | tr -d "'")"
if [ "$slug" != "frigate-ptz" ]; then
  echo "This is not the existing frigate-ptz add-on; refusing to modify" >&2
  exit 1
fi

# This is a fail-closed check. A missing/private/unpublished image is not an
# acceptable fallback to compiling the frontend on the Home Assistant host.
token_json="$(curl --fail --silent --show-error --location --max-time 20 \
  "https://ghcr.io/token?scope=repository:michlimek/frigate:pull&service=ghcr.io")" || {
  echo "Could not contact GHCR; leaving the add-on unchanged" >&2
  exit 1
}
token="$(printf '%s' "$token_json" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
if [ -z "$token" ]; then
  echo "Could not obtain an anonymous GHCR pull token; aborting" >&2
  exit 1
fi
status="$(curl --silent --show-error --location --max-time 30 \
  --output /dev/null --write-out '%{http_code}' \
  --header "Authorization: Bearer $token" \
  --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  "https://$registry/v2/michlimek/frigate/manifests/$version")" || {
  echo "Could not verify GHCR manifest; leaving the add-on unchanged" >&2
  exit 1
}
if [ "$status" != "200" ]; then
  echo "Prebuilt image $image:$version is not publicly pullable (HTTP $status); aborting" >&2
  exit 1
fi

backup="$config.bak-before-prebuilt-post3"
if [ -e "$backup" ]; then
  echo "Backup already exists: $backup; refusing overwrite" >&2
  exit 1
fi
if ! grep -Eq '^version:[[:space:]]*' "$config"; then
  echo "No version field; refusing to update manifest" >&2
  exit 1
fi

cp "$config" "$backup"
sed -e 's/^version:.*/version: "0.18.2.post3"/' \
    -e '/^image:[[:space:]]*/d' "$backup" > "$config.tmp"
printf '\nimage: %s\n' "$image" >> "$config.tmp"
mv "$config.tmp" "$config"
echo "Updated $config to verified prebuilt image $image:$version"
echo "Backup: $backup"
echo "Reload local add-ons in HA, then update the existing PTZ Fix add-on."
