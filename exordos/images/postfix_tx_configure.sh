#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

domain=$1
mode=$2
config=/etc/postfix-tx
install -d -m 0755 "$config"
install -d -o root -g root -m 0755 /persist/mail/tx/postfix
install -d -o exordos-mail-tx -g exordos-mail-tx -m 0750 /persist/mail/tx/data
sed "s/@DOMAIN@/$domain/g" /usr/local/share/exordos-mail/postfix-tx.cf >"$config/main.cf"
install -m 0644 /usr/share/postfix/master.cf.dist "$config/master.cf"

postconf -c "$config" -M -X smtp/inet submission/inet submissions/inet smtps/inet
postconf -c "$config" -M '587/inet=587 inet n - n - - smtpd'
postconf -c "$config" -M 'smtp-local/unix=smtp-local unix - - n - - smtp'
postconf -c "$config" -P 'smtp-local/unix/smtp_host_lookup=native'
printf '%s smtp-local:[localhost]:2525\n' "$domain" >"$config/transport"
printf '[localhost]:2525 secure match=localhost\n' >"$config/tls-policy"
if [[ "$mode" == mailbox ]]; then
    postconf -c "$config" -M '127.0.0.1:1587/inet=127.0.0.1:1587 inet n - n - - smtpd'
    postconf -c "$config" -P \
        '127.0.0.1:1587/inet/smtpd_tls_security_level=may' \
        '127.0.0.1:1587/inet/smtpd_tls_auth_only=no' \
        '127.0.0.1:1587/inet/smtpd_relay_restrictions=$exordos_calendar_relay_restrictions'
    printf 'calendar-scheduler OK\n' >"$config/calendar-logins"
    printf 'calendar-scheduler REJECT This login requires the calendar listener\n' >"$config/public-logins"
    postmap "hash:$config/calendar-logins" "hash:$config/public-logins"
    postconf -c "$config" -e \
        "exordos_calendar_relay_restrictions=check_sasl_access hash:$config/calendar-logins, reject" \
        "smtpd_relay_restrictions=check_sasl_access hash:$config/public-logins, permit_sasl_authenticated, reject"
else
    postconf -c "$config" -M '25/inet=25 inet n - n - - smtpd' '465/inet=465 inet n - n - - smtpd'
    postconf -c "$config" -P '465/inet/smtpd_tls_wrappermode=yes'
    postconf -c "$config" -e 'message_size_limit=52428800' 'defer_transports=smtp-local'
fi
postmap "hash:$config/transport" "hash:$config/tls-policy"
postfix -c "$config" check
