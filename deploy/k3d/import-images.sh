#!/usr/bin/env bash
# Imports locally built images into every node of a k3d cluster, and checks they arrived.
#   deploy/k3d/import-images.sh <cluster> <image:tag>...
#
# `k3d image import` can fail on a node and still exit 0: Cluster run 45284379949 logged
# "failed to import images in node 'k3d-supportx-server-0' ... ctr: open /k3d/images/...tar: no
# such file or directory", went on, and the install then waited 10 minutes for pods whose images
# never arrived. So the import is `--mode direct` (no shared tarball for a node to lose, as
# deploy-ha found), and afterwards each image is looked up in each node's containerd. A node
# missing one gets the whole import again, up to IMPORT_ATTEMPTS times; then it fails, naming the
# node and the image.
set -euo pipefail

cluster="${1:?usage: import-images.sh <cluster> <image:tag>...}"
shift
[ "$#" -gt 0 ] || { echo "import-images.sh: no images given" >&2; exit 2; }
attempts="${IMPORT_ATTEMPTS:-3}"

nodes() {  # the cluster's server and agent containers (never its load balancer or tools)
  docker ps --format '{{.Names}}' --filter "label=k3d.cluster=$cluster" --filter "label=k3d.role=server"
  docker ps --format '{{.Names}}' --filter "label=k3d.cluster=$cluster" --filter "label=k3d.role=agent"
}

missing() {  # prints "<node> <image>" for each image a node's containerd does not have
  local node image listed
  for node in $(nodes); do
    listed="$(docker exec "$node" ctr -n k8s.io images ls -q 2>/dev/null || true)"
    for image in "$@"; do
      # A local `name:tag` is stored as docker.io/library/name:tag.
      grep -qxF -e "$image" -e "docker.io/library/$image" <<<"$listed" || echo "$node $image"
    done
  done
}

[ -n "$(nodes)" ] || { echo "import-images.sh: cluster '$cluster' has no server or agent nodes" >&2; exit 1; }
for attempt in $(seq 1 "$attempts"); do
  k3d image import --mode direct "$@" -c "$cluster" || echo "k3d image import exited $? (attempt $attempt)"
  gaps="$(missing "$@")"
  if [ -z "$gaps" ]; then
    echo "images on every node after attempt $attempt: $*"
    exit 0
  fi
  echo "attempt $attempt of $attempts left images missing:"
  while read -r line; do echo "  $line"; done <<<"$gaps"
done
echo "::error title=k3d image import::images still missing after $attempts attempts" >&2
exit 1
