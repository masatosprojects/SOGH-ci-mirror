#!/usr/bin/env bash
# Run ON THE PI by the human, once:  sudo bash ~/sogh_harden.sh
# Conservative and reversible. No firewall change (avoids locking out SSH), no new network exposure.
set -u
LOG="$HOME/sogh_harden.log"
exec > >(tee -a "$LOG") 2>&1
echo "== sogh_harden $(date -Is)"
echo "-- 1. package update (security + fixes)"
apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
echo "-- 2. stop unneeded rpcbind (port 111)"
systemctl disable --now rpcbind.service rpcbind.socket 2>&1 || true
echo "-- 3. limit journal size (less SD wear / disk use)"
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=50M\nRuntimeMaxUse=30M\nCompress=yes\nSyncIntervalSec=5m\n' > /etc/systemd/journald.conf.d/sogh.conf
systemctl restart systemd-journald
echo "-- 4. effective sshd policy (read back)"
sshd -T 2>/dev/null | grep -E '^(passwordauthentication|pubkeyauthentication|permitrootlogin|kbdinteractiveauthentication) '
echo "-- 5. listening sockets after changes"
ss -tlnH | awk '{print $4}'
echo "-- 6. reboot needed?"; [ -f /var/run/reboot-required ] && echo "yes: please reboot once" || echo "no"
echo "== done. Undo rpcbind: sudo systemctl enable --now rpcbind ; undo journal: sudo rm /etc/systemd/journald.conf.d/sogh.conf"
