#!/usr/bin/env bash
# Run ON THE PI by the human, ONCE:  sudo bash ~/sogh_enable_admin.sh
# Installs a fixed, root-owned admin tool and a sudoers rule that lets the user "sogh" run ONLY these exact
# commands without a password. The tool cannot be edited by "sogh" (root:root 0755), so the allowed set
# cannot be widened without the human running sudo again. No shell, no package install, no network changes.
set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
TOOL=/usr/local/sbin/sogh-admin
cat > "$TOOL" <<'TOOLEOF'
#!/usr/bin/env bash
set -eu
case "${1:-}" in
  apt-upgrade)      apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade ;;
  rpcbind-off)      systemctl disable --now rpcbind.service rpcbind.socket ;;
  journal-limit)    mkdir -p /etc/systemd/journald.conf.d
                    printf '[Journal]\nSystemMaxUse=50M\nRuntimeMaxUse=30M\nCompress=yes\nSyncIntervalSec=5m\n' > /etc/systemd/journald.conf.d/sogh.conf
                    systemctl restart systemd-journald ;;
  sshd-effective)   sshd -T | grep -E '^(passwordauthentication|pubkeyauthentication|permitrootlogin|kbdinteractiveauthentication) ' ;;
  kernel-log)       dmesg | tail -200 ;;
  state-service)    case "${2:-}" in start|stop|restart|status|enable|disable) systemctl "$2" sogh-state.service ;; *) echo "usage"; exit 2;; esac ;;
  reboot)           systemctl reboot ;;
  *) echo "allowed: apt-upgrade rpcbind-off journal-limit sshd-effective kernel-log state-service {start|stop|restart|status|enable|disable} reboot"; exit 2 ;;
esac
TOOLEOF
chown root:root "$TOOL"; chmod 0755 "$TOOL"
RULE=/etc/sudoers.d/sogh-claude
TMP=$(mktemp)
{
  echo "# written by sogh_enable_admin.sh - exact commands only"
  for c in apt-upgrade rpcbind-off journal-limit sshd-effective kernel-log reboot \
           "state-service start" "state-service stop" "state-service restart" "state-service status" "state-service enable" "state-service disable"; do
    echo "sogh ALL=(root) NOPASSWD: $TOOL $c"
  done
} > "$TMP"
visudo -cf "$TMP" && install -m 0440 -o root -g root "$TMP" "$RULE" && echo "installed $RULE" || { echo "sudoers check FAILED - nothing installed"; exit 1; }
rm -f "$TMP"
echo "to revoke later: sudo rm $RULE $TOOL"
