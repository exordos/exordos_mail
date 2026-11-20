#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Install the mail data-plane packages.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get -o Acquire::Retries=3 update
cache_package=valkey-server
if ! apt-cache show "$cache_package" >/dev/null 2>&1; then
    cache_package=redis-server
fi
apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    postfix cyrus-imapd cyrus-caldav sasl2-bin libsasl2-modules libpam-pwdfile \
    dovecot-core rspamd "$cache_package" ca-certificates openssl python3

for user in exordos-mail-tx exordos-mail-sign; do
    getent passwd "$user" >/dev/null || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$user"
done
getent passwd exordos-mail-cache >/dev/null || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin exordos-mail-cache
ln -sfn "$(command -v "$cache_package")" /usr/local/lib/exordos-mail/valkey-server
