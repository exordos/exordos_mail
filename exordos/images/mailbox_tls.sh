#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
umask 077

domain="${1,,}"
domain="${domain%.}"
tls=$2
mode=${3:-}
[[ "$domain" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]
exec 9>"$tls/.lock"
flock 9
stage=$(mktemp -d -- "$tls/.tls.XXXXXX")
trap 'find "$stage" -depth -delete' EXIT

ca="$tls/ca.crt"
ca_key="$tls/ca.key"
renew_before=$((30 * 24 * 60 * 60))
reload=false
case "$mode" in
    --reload|--migrate-legacy-tx) reload=true ;;
esac
if [[ "$mode" == --migrate-legacy-tx && ( ! -s "$ca" || ! -s "$ca_key" || ! -s "$tls/rx.crt" ) ]]; then
    echo 'Configure the mail instance and distribute its CA before rotating legacy SMTP TLS.' >&2
    exit 1
fi
created_ca=false
if [[ ! -e "$ca" ]]; then
    if [[ ! -e "$ca_key" ]]; then
        openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$stage/ca.key" 2>/dev/null
        mv -- "$stage/ca.key" "$ca_key"
    fi
    openssl req -x509 -key "$ca_key" -sha256 -days 3650 -subj '/CN=Exordos Mail CA' \
        -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
        -addext 'keyUsage=critical,keyCertSign,cRLSign' -out "$stage/ca.crt"
    chmod 0644 "$stage/ca.crt"
    mv -- "$stage/ca.crt" "$ca"
    created_ca=true
fi
if ! openssl x509 -in "$ca" -noout -checkend "$renew_before" >/dev/null; then
    echo 'Mail CA expires within 30 days. Replace the CA and distribute its trust anchor.' >&2
fi
if [[ "$mode" == --prepare-ca ]]; then
    exit 0
fi

make_tls() {
    local role=$1 group=$2
    local cert="$tls/$role.crt" key="$tls/$role.key" archive="$tls/tx-legacy.crt"
    local signing_key subject issuer
    local dns_names="DNS:mail.$domain,DNS:localhost"
    if [[ -s "$cert" && -s "$key" ]] &&
        [[ "$(openssl x509 -in "$cert" -pubkey -noout)" == "$(openssl pkey -in "$key" -passin pass: -pubout)" ]]; then
        subject=$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253)
        issuer=$(openssl x509 -in "$cert" -noout -issuer -nameopt RFC2253)
        if [[ "$subject" == "subject=CN=Exordos Mail $role" ]]; then
            if [[ "$mode" == --migrate-legacy-tx ]]; then
                if [[ -s "$archive" ]] && openssl verify -no_check_time -verify_hostname "mail.$domain" \
                    -CAfile "$ca" -no-CApath -no-CAstore "$cert" >/dev/null; then
                    return
                fi
                echo 'Legacy SMTP rotation requires the original Exim certificate or a verified prior migration.' >&2
                return 1
            fi
            # Reissue the generated leaf when the instance CA changes.
            if openssl verify -CAfile "$ca" -no-CApath -no-CAstore "$cert" >/dev/null 2>&1 &&
                openssl x509 -in "$cert" -noout -checkend "$renew_before" >/dev/null; then
                return
            fi
        elif [[ "$role" == tx && "$mode" == --migrate-legacy-tx ]]; then
            if ! [[ ( "${subject,,}" == "subject=c=us,o=$domain,cn=$domain" ||
                       "${subject,,}" == "subject=c=us,o=$domain.,cn=$domain." ) &&
                     "${subject#subject=}" == "${issuer#issuer=}" &&
                     -z "$(openssl x509 -in "$cert" -noout -ext subjectAltName 2>/dev/null)" ]] ||
                ! openssl verify -check_ss_sig -no_check_time -CAfile "$cert" -no-CApath -no-CAstore "$cert" >/dev/null; then
                echo 'Legacy SMTP rotation requires an image-generated Exim certificate for this domain.' >&2
                return 1
            fi
            if [[ -e "$archive" ]] && ! cmp -s "$cert" "$archive"; then
                echo 'The SMTP certificate differs from the existing legacy archive.' >&2
                return 1
            fi
            install -m 0644 -- "$cert" "$stage/tx-legacy.crt"
        elif [[ "$subject" != "subject=CN=mail.$domain" || "${subject#subject=}" != "${issuer#issuer=}" ]]; then
            if ! openssl x509 -in "$cert" -noout -checkend "$renew_before" >/dev/null; then
                printf 'Operator-managed TLS certificate %s expires within 30 days\n' "$cert" >&2
            fi
            return
        elif openssl x509 -in "$cert" -noout -checkend "$renew_before" >/dev/null ||
            { [[ "$created_ca" == true ]] && openssl x509 -in "$cert" -noout -checkend 0 >/dev/null; }; then
            # Keep the legacy self-signed leaf while trust is being prepared.
            return
        fi
    elif [[ "$role" == tx && "$mode" == --migrate-legacy-tx ]]; then
        echo 'Legacy SMTP rotation requires a matching certificate and private key.' >&2
        return 1
    fi

    openssl x509 -in "$ca" -noout -checkend 0 >/dev/null || {
        echo 'Cannot issue a server certificate with an expired Mail CA.' >&2
        return 1
    }
    signing_key="$key"
    if [[ ! -s "$key" ]]; then
        signing_key="$stage/$role.key"
        openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$signing_key" 2>/dev/null
        chown root:"$group" "$signing_key"
        chmod 0640 "$signing_key"
    fi
    openssl req -new -key "$signing_key" -subj "/CN=Exordos Mail $role" -out "$stage/$role.csr"
    if [[ "$role" == tx && ( -e "$stage/tx-legacy.crt" || -e "$archive" ) ]]; then
        dns_names+=",DNS:$domain"
    fi
    cat >"$stage/extensions" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$dns_names
EOF
    openssl x509 -req -in "$stage/$role.csr" -CA "$ca" -CAkey "$ca_key" \
        -set_serial "0x$(openssl rand -hex 16)" -sha256 -days 90 \
        -extfile "$stage/extensions" -out "$stage/$role.crt"
    chmod 0644 "$stage/$role.crt"
    if [[ "$role" == tx && -e "$stage/tx-legacy.crt" ]]; then
        openssl verify -x509_strict -purpose sslserver -verify_hostname "mail.$domain" \
            -CAfile "$ca" -no-CApath -no-CAstore "$stage/$role.crt"
        if [[ ! -e "$archive" ]]; then
            mv -- "$stage/tx-legacy.crt" "$archive"
        fi
    fi
    if [[ "$reload" == true ]]; then
        touch "$tls/.reload"
    fi
    if [[ "$signing_key" != "$key" ]]; then
        mv -- "$signing_key" "$key"
    fi
    mv -- "$stage/$role.crt" "$cert"
}

if [[ "$mode" != --migrate-legacy-tx ]]; then
    make_tls rx mail
fi
make_tls tx root
# Keep local TLS clients working during the transition from self-signed leaves.
cat "$ca" "$tls/rx.crt" "$tls/tx.crt" >"$stage/trust.crt"
chmod 0644 "$stage/trust.crt"
if ! cmp -s "$stage/trust.crt" "$tls/trust.crt"; then
    mv -- "$stage/trust.crt" "$tls/trust.crt"
fi
if [[ "$reload" == true && -e "$tls/.reload" ]]; then
    systemctl try-restart exordos-mail-rx.service exordos-mail-tx.service exordos-mail-cyrus.service
    unlink "$tls/.reload"
fi
