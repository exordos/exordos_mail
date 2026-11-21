#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

copy_missing() {
    local source=$1 destination=$2 staged
    if [[ -e "$destination" ]]; then return; fi
    staged=$(mktemp "${destination}.XXXXXX")
    if ! install -m 0600 -- "$source" "$staged" || ! mv -T -- "$staged" "$destination"; then
        unlink "$staged"
        return 1
    fi
}

import_keys() {
    local source=$1 state=$2
    local key="$state/tls/tx.key" cert="$state/tls/tx.crt"
    local legacy_key="$source/exim.key" legacy_cert="$source/exim.crt"
    install -d -m 0755 "$state" "$state/tls"
    if [[ ! -e "$state/tx" ]]; then install -d -m 0751 "$state/tx"; fi
    (
        flock 9
        if [[ -s "$source/dkim/platform.private" && ! -e "$state/tx/platform.private" ]]; then
            openssl pkey -in "$source/dkim/platform.private" -passin pass: -noout
            copy_missing "$source/dkim/platform.private" "$state/tx/platform.private"
        fi
        if [[ -e "$key" && -e "$cert" ]]; then exit 0; fi
        if [[ ! -e "$legacy_key" && ! -e "$legacy_cert" ]]; then exit 0; fi
        local key_input="$legacy_key" cert_input="$legacy_cert" key_pub cert_pub
        if [[ -e "$key" ]]; then key_input="$key"; fi
        if [[ -e "$cert" ]]; then cert_input="$cert"; fi
        key_pub=$(openssl pkey -in "$key_input" -passin pass: -pubout)
        cert_pub=$(openssl x509 -in "$cert_input" -pubkey -noout)
        if [[ "$key_pub" != "$cert_pub" ]]; then
            printf 'Legacy TLS certificate does not match its private key\n' >&2
            return 1
        fi
        copy_missing "$key_input" "$key"
        copy_missing "$cert_input" "$cert"
    ) 9>"$state/.legacy-keys.lock"
}

no_active_exim() {
    local binary=$1 process
    for process in /proc/[0-9]*/exe; do
        if [[ "$process" -ef "$binary" ]]; then return 1; fi
    done
}

prepare_root() {
    local unit count guard binary held_binary created_guard=false was_running=false moved_binary=false
    local -a exim
    mountpoint -q /persist
    if [[ -f /usr/local/share/exordos-mail/postfix-tx.cf ]]; then return; fi
    exec 8>/run/lock/exordos-mail-legacy-upgrade.lock
    flock 8
    if [[ -x /usr/sbin/exim4 || -x /usr/sbin/.exordos-mail-upgrade/exim4 ]]; then
        binary=/usr/sbin/exim4
        exim=("$binary")
        unit=exim4.service
    elif [[ -x /usr/local/lib/exordos-mail/exim4 || -x /usr/local/lib/exordos-mail/.exordos-mail-upgrade/exim4 ]]; then
        binary=/usr/local/lib/exordos-mail/exim4
        exim=("$binary" -C /etc/exordos-mail/exim.conf)
        unit=exordos-mail-tx.service
    else
        printf 'Cannot locate the old SMTP engine to verify its queue\n' >&2
        return 1
    fi

    held_binary="${binary%/*}/.exordos-mail-upgrade/exim4"
    if [[ ! -e "$binary" ]]; then exim[0]=$held_binary; fi
    import_keys /etc/exim4 /persist/mail
    count=$("${exim[@]}" -bpc)
    if [[ "$count" != 0 ]]; then
        "${exim[@]}" -q
        printf 'Root replacement waits for %s messages in the Exim queue\n' "$count" >&2
        return 1
    fi
    # The hypervisor can restart the VM as soon as the agent reports readiness.
    sync -f /persist/mail
    if systemctl is-active --quiet "$unit"; then was_running=true; fi
    guard="/etc/systemd/system/$unit.d/90-exordos-postfix-upgrade.conf"
    if [[ ! -e "$guard" ]]; then
        install -d -m 0755 "${guard%/*}"
        printf '[Unit]\nConditionPathExists=!%s\n' "$guard" >"$guard"
        created_guard=true
    fi
    if systemctl daemon-reload && systemctl stop "$unit"; then
        # Disable local sendmail injection until Core replaces the root.
        if [[ "${exim[0]}" != "$held_binary" ]] &&
            install -d -o root -g root -m 0700 "${held_binary%/*}" &&
            mv -T -- "$binary" "$held_binary"; then
            moved_binary=true
            exim[0]=$held_binary
        fi
        if [[ "${exim[0]}" == "$held_binary" ]] &&
            no_active_exim "$held_binary" && count=$("${exim[@]}" -bpc) && [[ "$count" == 0 ]]; then
            return
        fi
    fi
    # A client may have queued mail between the first check and the stop.
    if [[ "$moved_binary" == true ]]; then mv -T -- "$held_binary" "$binary"; fi
    if [[ "$created_guard" == true ]]; then
        unlink "$guard"
        systemctl daemon-reload
        if [[ "$was_running" == true ]]; then systemctl start "$unit"; fi
    fi
    return 1
}

case "${1:-}" in
    import) import_keys "$2" "$3" ;;
    prepare-root) prepare_root ;;
    *) printf 'Usage: %s import SOURCE STATE | prepare-root\n' "$0" >&2; exit 2 ;;
esac
