#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

mountpoint -q /persist
domain="$1"
[[ "$domain" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]
assets=/usr/local/share/exordos-mail
state=/persist/mail

install -d -m 0755 "$state" "$state/control" "$state/cyrus" "$state/tls"
install -d -o cyrus -g mail -m 0750 "$state/cyrus/config" "$state/cyrus/spool" "$state/cyrus/sieve"
install -d -o cyrus -g mail -m 0755 /run/exordos-mail
install -d -o root -g mail -m 0750 /run/exordos-mail/saslauthd
install -d -o exordos-mail-cache -g exordos-mail-cache -m 0750 "$state/valkey"
if [[ ! -d "$state/postfix/private" ]]; then
    install -d -m 0755 "$state/postfix"
    cp -an /var/spool/postfix/. "$state/postfix/"
fi
if [[ ! -d "$state/cyrus/config/user" ]]; then
    cp -an /var/lib/cyrus/. "$state/cyrus/config/"
fi

if [[ ! -s "$state/tx/scheduler.secret" ]]; then
    (umask 077; openssl rand -hex 32 >"$state/tx/scheduler.secret.new")
    mv "$state/tx/scheduler.secret.new" "$state/tx/scheduler.secret"
fi
if [[ ! -s "$state/tx/scheduler.hash" ]]; then
    (umask 077; openssl passwd -6 -stdin <"$state/tx/scheduler.secret" >"$state/tx/scheduler.hash.new")
    mv "$state/tx/scheduler.hash.new" "$state/tx/scheduler.hash"
fi
if [[ ! -s "$state/control/provision.secret" ]]; then
    (umask 077; openssl rand -hex 32 >"$state/control/provision.secret")
fi
if [[ ! -s "$state/control/provision.hash" ]]; then
    (umask 077; openssl passwd -6 -stdin <"$state/control/provision.secret" >"$state/control/provision.hash")
fi

getent group exordos-mail-cyrus >/dev/null || groupadd --system exordos-mail-cyrus
if ! id -nG cyrus | tr ' ' '\n' | grep -Fxq exordos-mail-cyrus; then
    usermod -a -G exordos-mail-cyrus cyrus
fi
install -d -m 0755 /etc/exordos-mail /etc/rspamd/local.d
# Render configs without sending secrets via command line arguments or logs.
python3 - "$domain" <<'PY'
from pathlib import Path
import grp
import os
import sys
import tempfile

assets = Path("/usr/local/share/exordos-mail")
domain = sys.argv[1]
secret = Path("/persist/mail/tx/scheduler.secret").read_text().strip()
for name, destination, permissions, group in [
    ("imapd.conf", "/etc/imapd.conf", 0o640, "exordos-mail-cyrus"),
    ("postfix.cf", "/etc/postfix/main.cf", 0o644, "root"),
]:
    path = Path(destination)
    content = (assets / name).read_text().replace("@DOMAIN@", domain)
    content = content.replace("@CALENDAR_SECRET@", secret)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        staged = Path(output.name)
        try:
            output.write(content)
            output.flush()
            os.fchown(output.fileno(), 0, grp.getgrnam(group).gr_gid)
            os.fchmod(output.fileno(), permissions)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
PY
install -m 0644 "$assets/cyrus.conf" /etc/cyrus.conf

# The explicit domain is the only one Postfix can accept. Virtual aliases
# redirect unknown addresses to the discard transport per recipient.
regex_domain=${domain//./\\.}
printf '/@%s$/ lmtp:unix:/run/exordos-mail/lmtp\n/^unknown@discard\\.invalid$/ discard:Unknown recipient\n' \
    "$regex_domain" >/etc/postfix/exordos-mail-transport
postconf -M -X smtp/inet
postconf -M '2525/inet=2525 inet n - n - - smtpd' 'lmtp/unix=lmtp unix - - n - - lmtp'
postfix check

for pam_service in imap http HTTP; do
    cat >"/etc/pam.d/$pam_service" <<'PAM'
auth required pam_pwdfile.so pwdfile=/persist/mail/control/imap.passwd
account required pam_permit.so
PAM
done

cat >/etc/rspamd/local.d/worker-proxy.inc <<'RSPAMD'
bind_socket = "127.0.0.1:11332";
milter = yes;
upstream "local" {
  default = yes;
  self_scan = yes;
}
RSPAMD
cat >/etc/rspamd/local.d/redis.conf <<'RSPAMD'
servers = "/run/exordos-mail-valkey/valkey.sock";
RSPAMD
cat >/etc/rspamd/local.d/actions.conf <<'RSPAMD'
reject = null;
greylist = null;
RSPAMD
printf 'check_local = true;\n' >/etc/rspamd/local.d/spf.conf
printf 'check_local = true;\n' >/etc/rspamd/local.d/dkim.conf
cat >/etc/rspamd/local.d/dmarc.conf <<'RSPAMD'
check_local = true;
actions {
  reject = "reject";
}
RSPAMD
# Use the Received chain only when the connecting peer is a configured MX.
if [[ ! -e "$state/control/trusted-mx" ]]; then
    install -m 0644 /dev/null "$state/control/trusted-mx"
fi
cat >/etc/rspamd/local.d/external_relay.conf <<'RSPAMD'
enabled = true;
rules {
  mx {
    strategy = "ip_map";
    ip_map = "/persist/mail/control/trusted-mx";
  }
}
RSPAMD

rspamd_state="$state/rspamd"
# Keep the existing include path on VMs that already migrated their RRD.
rspamd_state_config=/etc/rspamd/exordos-mail-rrd.inc
rspamd_workdir=/var/lib/rspamd
install -d -o _rspamd -g _rspamd -m 0750 "$rspamd_state"
(
    staged_config=$(mktemp -- "$rspamd_state_config.XXXXXX")
    staged_paths=("$staged_config")
    staged_state=
    trap 'rm -f -- "${staged_paths[@]}"; if [[ -n "$staged_state" ]]; then rm -rf -- "$staged_state"; fi' EXIT
    cat >"$staged_config" <<'RSPAMD'
control_socket = "/run/exordos-mail-rspamd/rspamd.sock mode=0600";
cache_file = "/var/cache/exordos-mail-rspamd/symbols.cache";
hs_cache_dir = "/var/cache/exordos-mail-rspamd/";
RSPAMD
    chmod 0644 "$staged_config"

    rspamd_options=$(realpath -m -- /etc/rspamd/local.d/options.inc)
    state_include='.include(try=true,priority=10) "/etc/rspamd/exordos-mail-rrd.inc"'
    legacy_include='.include(priority=10) "/etc/rspamd/exordos-mail-rrd.inc"'
    if ! grep -Fxq -e "$state_include" -e "$legacy_include" "$rspamd_options" 2>/dev/null; then
        staged_options=$(mktemp -- "$rspamd_options.XXXXXX")
        staged_paths+=("$staged_options")
        if [[ -e "$rspamd_options" ]]; then
            cp -p -- "$rspamd_options" "$staged_options"
        else
            chmod 0644 "$staged_options"
        fi
        printf '\n%s\n' "$state_include" >>"$staged_options"
        mv -- "$staged_options" "$rspamd_options"
    fi

    if ! mountpoint -q "$rspamd_workdir"; then
        if [[ ! -f "$rspamd_state/.exordos-directory" ]]; then
            staged_state=$(mktemp -d -- "$state/.rspamd.XXXXXX")
            chown _rspamd:_rspamd "$staged_state"
        fi
        # Stop the controller before copying its counters and mapped data.
        systemctl stop exordos-mail-rspamd.service
        if [[ -n "$staged_state" ]]; then
            copied=true
            if ! runuser -u _rspamd -- bash -eu -s -- \
                "$rspamd_state" "$rspamd_workdir" "$staged_state" <<'MIGRATE_RSPAMD'; then
source_dir=$2
staged=$3
cp -a --no-preserve=ownership -- "$1/." "$staged/"
shopt -s dotglob nullglob
for file in "$source_dir/"*; do
    case "${file##*/}" in
        rspamd.sock|symbols.cache|*.hs|*.hsmp|*.hsmc|*.unser) continue ;;
    esac
    cp -a --no-preserve=ownership --update=none -- "$file" "$staged/"
done
touch "$staged/.exordos-directory"
MIGRATE_RSPAMD
                copied=false
            fi
            if [[ "$copied" != true ]] || ! mv -T --exchange --no-copy -- "$staged_state" "$rspamd_state"; then
                systemctl start exordos-mail-rspamd.service
                exit 1
            fi
        fi

        if ! mount --bind "$rspamd_state" "$rspamd_workdir"; then
            if [[ -n "$staged_state" ]] &&
                ! mv -T --exchange --no-copy -- "$staged_state" "$rspamd_state"; then
                # Keep the backup when the data volume does not allow a rollback.
                staged_state=
            fi
            systemctl start exordos-mail-rspamd.service
            exit 1
        fi
    fi
    if [[ "$(stat -Lc '%d:%i' "$rspamd_workdir")" != "$(stat -Lc '%d:%i' "$rspamd_state")" ]]; then
        printf 'Rspamd work directory is mounted from another volume\n' >&2
        exit 1
    fi
    if ! cmp -s "$staged_config" "$rspamd_state_config" &&
        ! mv -- "$staged_config" "$rspamd_state_config"; then
        systemctl start exordos-mail-rspamd.service
        exit 1
    fi
)

systemctl restart exordos-mail-valkey.service \
    exordos-mail-saslauthd.service exordos-mail-cyrus.service exordos-mail-rspamd.service
if [[ -s "$state/control/recipients.db" ]]; then
    systemctl restart exordos-mail-rx.service
else
    systemctl stop exordos-mail-rx.service
fi
