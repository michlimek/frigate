#!/usr/bin/env bash
# External AMD64 Docker/WSL2 workstation only. Never run on HA OS.
set -euo pipefail

if [[ -v SUPERVISOR_TOKEN || ( -f /.dockerenv && -e /data/options.json ) ]]; then
  echo "Refusing to build inside a Home Assistant add-on" >&2
  exit 1
fi

command -v docker >/dev/null || { echo "Docker CLI is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v make >/dev/null || { echo "make is required" >&2; exit 1; }
root="$(git rev-parse --show-toplevel)"
cd "$root"
branch="$(git symbolic-ref --short HEAD)"
if [[ "$branch" != "release/0.18.2" ]]; then
  echo "Checkout release/0.18.2 before publishing, got $branch" >&2
  exit 1
fi

version="$(awk '$1 == "VERSION" && $2 == "=" {print $3}' Makefile)"
if [[ ! "$version" =~ ^0\.18\.2\.post[0-9]+$ ]]; then
  echo "Unexpected release version: $version" >&2
  exit 1
fi
if [[ ! -f frigate_ptz/config.yaml ]] || ! grep -qF "version: \"$version\"" frigate_ptz/config.yaml; then
  echo "Add-on version mismatch" >&2
  exit 1
fi
if ! grep -q '^image: ghcr.io/michlimek/frigate$' frigate_ptz/config.yaml; then
  echo "Add-on is not configured to pull GHCR image" >&2
  exit 1
fi
if [[ -f frigate_ptz/Dockerfile ]]; then
  echo "Unsafe local Dockerfile still present in HA add-on" >&2
  exit 1
fi

make version
short_sha="$(git rev-parse --short=7 HEAD)"
image="ghcr.io/michlimek/frigate:$version"
immutable="ghcr.io/michlimek/frigate:$version-$short_sha-amd64"
printf 'Building %s on EXTERNAL Docker host\n' "$image"
docker buildx build --platform linux/amd64 --load \
  --file docker/ptz-vehicle-visits-release.Dockerfile \
  --tag "$image" --tag "$immutable" .

docker run --rm --workdir /opt/frigate --entrypoint python3 "$image" \
  -m unittest -v \
  frigate.test.test_vehicle_visit_matching \
  frigate.test.test_vehicle_visit_store \
  frigate.test.test_ptz_movement_prediction

docker run --rm --entrypoint /bin/sh "$image" -ec \
  'test -f /opt/frigate/web/index.html && test -f /opt/frigate/frigate/vehicle_visits/store.py && test -f /opt/frigate/migrations/036_create_vehicle_visit_tables.py'

# Validate a real Frigate process and the migration in an isolated Docker volume.
config_volume="frigate-release-config-$short_sha"
media_volume="frigate-release-media-$short_sha"
name="frigate-release-smoke-$short_sha"
docker volume create "$config_volume" >/dev/null
docker volume create "$media_volume" >/dev/null
cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker volume rm "$config_volume" "$media_volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker run --rm \
  -v "$config_volume:/config" \
  --entrypoint /bin/sh "$image" -c \
  "printf 'mqtt:\n  enabled: false\ncameras: {}\n' >/config/config.yml"
docker run -d --name "$name" --shm-size 256m \
  -v "$config_volume:/config" -v "$media_volume:/media/frigate" \
  --tmpfs /tmp/cache:rw,size=100m \
  -p 127.0.0.1:5019:5000 "$image" >/dev/null
ready=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:5019/api/version" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 5
done
if [[ "$ready" != 1 ]]; then
  docker logs "$name"
  echo "Frigate smoke test did not start" >&2
  exit 1
fi
curl -fsS "http://127.0.0.1:5019/api/vehicle_visits?camera=all" >/dev/null
docker exec "$name" python3 -c \
  "import sqlite3; d=sqlite3.connect('/config/frigate.db'); names={r[0] for r in d.execute('select name from sqlite_master where type = ?', ('table',))}; assert {'vehiclevisit', 'vehiclevisitevent'} <= names, names"
cleanup
trap - EXIT

if [[ "$(printenv PUBLISH || true)" != 1 ]]; then
  echo "All local tests passed. Image is NOT published."
  echo "After docker login ghcr.io, rerun with PUBLISH=1 to publish."
  exit 0
fi
echo "Publishing pretested image to GHCR (docker login required)"
docker push "$immutable"
docker push "$image"
echo "Published $image"
echo "Make the GHCR package PUBLIC and verify anonymous manifest access before HA upgrade."
