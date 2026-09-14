#!/bin/bash
# EC2 user data for g6.xlarge on a Deep Learning AMI (Ubuntu 24.04, Base GPU).
# - Installs Docker + Compose plugin if missing
# - Finds the 150 GB data EBS volume (NVMe name may vary), formats on first use, mounts at /data
# - Moves Docker's data-root to /data/docker
# - Clones this repo to /data/nekohasekai (tailscale-nodes: vLLM on the Mesh)
# User data runs on first boot only. Later boots: docker is enabled and the stack has
# restart: unless-stopped, so it comes back on its own.
set -euxo pipefail
exec > >(tee -a /var/log/userdata.log | logger -t userdata) 2>&1

DATA_MOUNT=/data
DATA_LABEL=data
REPO_DIR="$DATA_MOUNT/nekohasekai"

# ---------- 1. Find the data volume ----------
# EBS disks only: g6 also has a local NVMe instance store ("Amazon EC2 NVMe Instance Storage")
# that is wiped on stop. The root EBS disk is skipped because it has mounted partitions.
DATA_DEV=""
for i in $(seq 1 150); do   # wait up to 5 min so the volume can be attached after launch
  for d in $(lsblk -dno NAME,MODEL | awk '/Elastic Block Store/{print $1}'); do
    mounts=$(lsblk -no MOUNTPOINT "/dev/$d")
    [ -n "${mounts//[[:space:]]/}" ] && continue
    DATA_DEV="/dev/$d"; break
  done
  [ -n "$DATA_DEV" ] && break
  sleep 2
done
[ -z "$DATA_DEV" ] && { echo "No data volume found; aborting"; exit 1; }
echo "Data volume: $DATA_DEV"

# ---------- 2. Format on first use, mount by UUID ----------
# Blank disk only (no filesystem, no partition table): never wipe existing data.
if [ -z "$(blkid -o value "$DATA_DEV" || true)" ]; then
  mkfs.ext4 -L "$DATA_LABEL" "$DATA_DEV"
fi
UUID=$(blkid -s UUID -o value "$DATA_DEV" || true)
[ -z "$UUID" ] && { echo "$DATA_DEV has no filesystem UUID (partitioned?); aborting"; exit 1; }
mkdir -p "$DATA_MOUNT"
grep -q "UUID=$UUID" /etc/fstab || echo "UUID=$UUID $DATA_MOUNT ext4 defaults,nofail 0 2" >> /etc/fstab
systemctl daemon-reload
mountpoint -q "$DATA_MOUNT" || mount "$DATA_MOUNT"
mkdir -p "$DATA_MOUNT/docker" "$DATA_MOUNT/hf"

# ---------- 3. Docker + Compose ----------
if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
# Ubuntu's own docker.io has no docker-compose-plugin package; its name there is docker-compose-v2.
docker compose version || { apt-get update; apt-get install -y docker-compose-plugin || apt-get install -y docker-compose-v2; }

# ---------- 4. GPU runtime check ----------
if ! command -v nvidia-smi >/dev/null; then
  echo "WARNING: NVIDIA driver not found. Use a Deep Learning AMI or install the driver manually."
fi
if ! command -v nvidia-ctk >/dev/null; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update && apt-get install -y nvidia-container-toolkit
fi

# ---------- 5. Docker data-root on /data ----------
systemctl stop docker docker.socket || true
# Recent Docker defaults to the containerd image store, which ignores data-root
# and writes images to /var/lib/containerd on the root disk. Force overlay2.
cat > /etc/docker/daemon.json <<EOF
{
  "data-root": "$DATA_MOUNT/docker",
  "features": { "containerd-snapshotter": false },
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
EOF
nvidia-ctk runtime configure --runtime=docker || true
# On later boots Docker must wait for /data; otherwise it starts a fresh, empty data-root
# on the root disk. If the volume is missing, Docker fails to start instead.
mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nRequiresMountsFor=%s\n' "$DATA_MOUNT" > /etc/systemd/system/docker.service.d/data-mount.conf
systemctl daemon-reload
systemctl enable docker
systemctl restart docker
usermod -aG docker ubuntu || true

# ---------- 6. Repo ----------
[ -d "$REPO_DIR/.git" ] || git clone https://github.com/minlaxz/nekohasekai "$REPO_DIR"
chown -R ubuntu:ubuntu "$REPO_DIR" "$DATA_MOUNT/hf"

echo "User data finished. Start vLLM once with:"
echo "  cd $REPO_DIR/tailscale-nodes"
echo "  cp .env.sample .env && vim .env"
echo "  docker compose up -d && docker compose logs -f"
