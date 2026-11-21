#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

mountpoint -q /persist
source /etc/exordos_metapaas/mail.env
domain="${MAIL_DOMAIN,,}"
domain="${domain%.}"
mode="${MAIL_MODE:-smtp_only}"
[[ "$domain" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]
case "$mode" in
    smtp_only|mailbox) ;;
    *) printf 'Unknown mail mode: %s\n' "$mode" >&2; exit 1 ;;
esac

exec 9>/run/lock/exordos-mail-configure.lock
flock 9
state=/persist/mail
control="$state/control"
mode_file=/run/exordos-mail-mode
lib=/usr/local/lib/exordos-mail
tx=exordos-mail-tx.service
tx_helpers=(exordos-mail-tx-auth.service exordos-mail-tx-filter.service)
mailbox_units=(
    exordos-mail-rx.service exordos-mail-cyrus.service exordos-mail-saslauthd.service
    exordos-mail-rspamd.service exordos-mail-valkey.service
)
install -d -m 0755 "$state" "$control" "$state/tls" /etc/exordos-mail
bash "$lib/legacy-keys" import /etc/exim4 "$state"
install -d -o root -g exordos-mail-sign -m 0751 "$state/tx"
unlink "$mode_file" 2>/dev/null || true

previous=$(cat "$control/mode" 2>/dev/null || true)
if [[ "$previous" != "$mode" ]]; then
    systemctl stop "$tx" "${tx_helpers[@]}" "${mailbox_units[@]}"
    # Credentials and recipient maps belong to the applied mode.
    install -o root -g dovecot -m 0640 /dev/null "$control/tx.passwd"
    for file in imap.passwd senders recipients.db target.json; do
        if [[ -e "$control/$file" ]]; then unlink "$control/$file"; fi
    done
    printf '%s\n' "$mode" >"$control/mode"
fi

"$lib/mailbox-tls" "$domain" "$state/tls"
if [[ ! -s "$state/tx/platform.private" ]]; then
    umask 077
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$state/tx/platform.private.new"
    mv "$state/tx/platform.private.new" "$state/tx/platform.private"
    umask 022
fi
public_key=$(openssl pkey -in "$state/tx/platform.private" -pubout -outform DER | openssl base64 -A)
printf 'platform._domainkey IN TXT ( "v=DKIM1; k=rsa; " "p=%s" "%s" )\n' \
    "${public_key:0:240}" "${public_key:240}" >"$state/tx/platform.txt"

chown root:exordos-mail-sign "$state/tx/platform.private"
chmod 0640 "$state/tx/platform.private"
chmod 0600 "$state/tls/tx.key"
chown root:root "$state/tls/tx.key"
if [[ ! -e "$control/tx.passwd" ]]; then
    install -o root -g dovecot -m 0640 /dev/null "$control/tx.passwd"
fi
chown root:dovecot "$control/tx.passwd"
chmod 0640 "$control/tx.passwd"
if [[ -e "$control/senders" ]]; then
    chown root:exordos-mail-sign "$control/senders"
    chmod 0640 "$control/senders"
fi
bash "$lib/postfix-tx-configure" "$domain" "$mode"

if [[ "$mode" == mailbox ]]; then
    "$lib/mailbox-configure" "$domain"
fi
systemctl restart "${tx_helpers[@]}" "$tx"
systemctl enable --now exordos-mail-tls-renew.timer
printf '%s\n' "$mode" >"$mode_file"
