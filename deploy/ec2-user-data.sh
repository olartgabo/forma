#!/bin/bash
# EC2 user data for Ubuntu 24.04 arm64. The launcher replaces FORMA_REF with
# the exact commit to deploy.
set -euxo pipefail
FORMA_REF=__FORMA_REF__
export DEBIAN_FRONTEND=noninteractive

# The Next.js production build needs more than 2 GB at peak.
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >>/etc/fstab

apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
  >/etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
snap install aws-cli --classic

git clone https://github.com/olartgabo/forma.git /opt/forma
git -C /opt/forma checkout --detach "$FORMA_REF"
bash /opt/forma/deploy/host-up.sh
