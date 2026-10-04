#!/usr/bin/env bash
# provision.sh: install what a Seedy runner VM needs: Docker, git, python3, jq and the GitHub Actions runner.
# cloud-init runs it at first boot. Run it while building a custom image (custom_image_id) and the marker
# file it leaves makes the boot-time run a no-op.
#
# Environment: RUNNER_VERSION [latest]   PREPULL_IMAGES [none; space-separated Docker images to bake in]
set -euo pipefail

MARKER=/opt/seedy-runner/.provisioned
RUNNER_DIR=/opt/actions-runner
RUNNER_VERSION=${RUNNER_VERSION:-latest}
PREPULL_IMAGES=${PREPULL_IMAGES:-}

if [ -f "$MARKER" ]; then
  echo "provision: already done ($(cat "$MARKER"))"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
# a runner lives for one job: background apt runs only steal CPU from Quartus. Rebuild the image to patch.
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service 2>/dev/null || true
apt-get update -q
apt-get install -y -q --no-install-recommends \
  docker.io git jq curl ca-certificates openssl python3 xz-utils tar iptables
systemctl enable --now docker

id runner >/dev/null 2>&1 || useradd --create-home --shell /bin/bash runner
usermod -aG docker runner

if [ "$RUNNER_VERSION" = latest ]; then
  RUNNER_VERSION=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name)
fi
RUNNER_VERSION=${RUNNER_VERSION#v}
rm -rf "$RUNNER_DIR" && mkdir -p "$RUNNER_DIR"
curl -fsSL "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz" \
  | tar -xz -C "$RUNNER_DIR"
"$RUNNER_DIR/bin/installdependencies.sh"

for image in $PREPULL_IMAGES; do
  echo "provision: pulling $image"
  docker pull --quiet "$image"
done

mkdir -p "$(dirname "$MARKER")"
echo "runner $RUNNER_VERSION, images: ${PREPULL_IMAGES:-none}, $(date -u +%FT%TZ)" > "$MARKER"
echo "provision: done"
