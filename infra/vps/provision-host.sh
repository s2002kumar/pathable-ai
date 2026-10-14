#!/bin/sh
# Prepare a fresh Ubuntu host to run PathAble's production Compose stack.
#
#   sudo sh infra/vps/provision-host.sh
#
# Idempotent: every step checks before it changes anything, so re-running it
# after an upgrade or a half-finished first run is safe. It never touches the
# application, its data or its secrets — those belong to deploy.sh.
#
# What it does, and why:
#   * packages from the Ubuntu archive only (docker.io, compose v2, buildx), so
#     unattended-upgrades patches the container runtime with the rest of the OS
#     and no third-party apt repository has to be trusted
#   * a swap file, because a 4 GB host building images while the API holds the
#     ~1 GB routing graph needs somewhere to put a transient peak other than the
#     OOM killer; swappiness is kept low so swap absorbs peaks rather than
#     paging the graph out
#   * key-only SSH for one named user, no root login
#   * a firewall that admits SSH, HTTP and HTTPS and nothing else
#   * fail2ban on SSH, bounded Docker logs, and automatic security updates with
#     a reboot in a quiet window when a kernel update needs one

set -eu

[ "$(id -u)" = "0" ] || { echo "run as root: sudo sh $0" >&2; exit 1; }

DEPLOY_USER="${DEPLOY_USER:-ubuntu}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
# 08:30 UTC is 04:30 in Waterloo (EDT) and 03:30 in winter (EST).
REBOOT_TIME_UTC="${REBOOT_TIME_UTC:-08:30}"

log() { printf '%s provision-host: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }

id "$DEPLOY_USER" >/dev/null 2>&1 || { log "no such user: $DEPLOY_USER"; exit 1; }
[ -s "/home/$DEPLOY_USER/.ssh/authorized_keys" ] || {
    log "refusing: $DEPLOY_USER has no authorized_keys; disabling passwords would lock everyone out"
    exit 1
}

# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
log "updating packages"
apt-get update -q
apt-get -y -q -o Dpkg::Options::=--force-confold full-upgrade
apt-get -y -q install --no-install-recommends \
    docker.io docker-compose-v2 docker-buildx \
    ufw fail2ban unattended-upgrades \
    git ca-certificates curl
usermod -aG docker "$DEPLOY_USER"

# ---------------------------------------------------------------------------
# Swap
# ---------------------------------------------------------------------------
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
    if [ ! -f /swapfile ]; then
        log "creating ${SWAP_SIZE} swap file"
        fallocate -l "$SWAP_SIZE" /swapfile
        chmod 600 /swapfile
        mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
cat > /etc/sysctl.d/90-pathable.conf <<'EOF'
# Swap is for transient peaks (image builds), not for the routing graph.
vm.swappiness = 10
EOF
sysctl -q -p /etc/sysctl.d/90-pathable.conf

# ---------------------------------------------------------------------------
# SSH: keys only, one user, no root
# ---------------------------------------------------------------------------
# sshd takes the FIRST value it reads for each keyword, and cloud-init's
# 50-cloud-init.conf turns PasswordAuthentication on. This file sorts first.
cat > /etc/ssh/sshd_config.d/00-pathable.conf <<EOF
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no
MaxAuthTries 3
AllowUsers ${DEPLOY_USER}
EOF
sshd -t
systemctl reload ssh
log "sshd: $(sshd -T | grep -E '^(passwordauthentication|permitrootlogin|allowusers) ' | tr '\n' ' ')"

# ---------------------------------------------------------------------------
# Firewall: SSH (rate-limited), HTTP, HTTPS (TCP, and UDP for HTTP/3)
# ---------------------------------------------------------------------------
# Docker publishes ports through its own iptables chains, which ufw does not
# see. That is why the Compose file publishes only Caddy's 80 and 443 — the
# database, API and web server have no host port at all.
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw limit 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
log "ufw: $(ufw status | grep -c ALLOW) allow/limit rules, default deny incoming"

cat > /etc/fail2ban/jail.d/pathable.local <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
systemctl enable --now fail2ban >/dev/null 2>&1
systemctl restart fail2ban

# ---------------------------------------------------------------------------
# Docker: bounded logs, containers survive a daemon upgrade
# ---------------------------------------------------------------------------
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" },
  "live-restore": true
}
EOF
systemctl enable docker >/dev/null 2>&1
systemctl restart docker

# ---------------------------------------------------------------------------
# Automatic security updates, with a reboot only when one is required
# ---------------------------------------------------------------------------
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat > /etc/apt/apt.conf.d/52pathable-unattended <<EOF
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "${REBOOT_TIME_UTC}";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
EOF

# ---------------------------------------------------------------------------
# Application directories
# ---------------------------------------------------------------------------
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0750 /srv/pathable
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 /srv/pathable/secrets
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0750 /var/backups/pathable

log "docker $(docker version --format '{{.Server.Version}}'), compose $(docker compose version --short)"
log "memory: $(free -m | awk '/^Mem:/ {print $2" MB"}'), swap: $(free -m | awk '/^Swap:/ {print $2" MB"}')"
if [ -f /var/run/reboot-required ]; then
    log "a reboot is required to finish the upgrade"
fi
log "done"
