#!/usr/bin/env bash

# Copyright 2026 Genesis Corporation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

set -eu
set -x
set -o pipefail


GC_PATH="/opt/exordos_metapaas"
GC_CFG_DIR=/etc/exordos_metapaas
WORK_DIR="/var/lib/exordos/exordos_metapaas"
VENV_PATH="$GC_PATH/.venv"
BOOTSTRAP_PATH="/var/lib/exordos/bootstrap/scripts"

SYSTEMD_SERVICE_DIR=/etc/systemd/system/

sudo install -d -m 0755 /usr/local/share/exordos-mail /usr/local/lib/exordos-mail
sudo bash "$GC_PATH/exordos/images/mailbox_deps.sh"
sudo install -m 0644 "$GC_PATH"/etc/mailbox/* /usr/local/share/exordos-mail/
sudo install -m 0755 "$GC_PATH/exordos/images/mail_configure.sh" /usr/local/bin/exordos-mail-configure
sudo install -m 0755 "$GC_PATH/exordos/images/mailbox_configure.sh" /usr/local/lib/exordos-mail/mailbox-configure
sudo install -m 0755 "$GC_PATH/exordos/images/mailbox_tls.sh" /usr/local/lib/exordos-mail/mailbox-tls
sudo install -m 0755 "$GC_PATH/exordos/images/postfix_tx_configure.sh" /usr/local/lib/exordos-mail/postfix-tx-configure
sudo install -m 0755 "$GC_PATH/exordos_mail/dataplane/legacy_keys.sh" /usr/local/lib/exordos-mail/legacy-keys
sudo install -m 0644 "$GC_PATH"/etc/systemd/exordos-mail-*.service "$SYSTEMD_SERVICE_DIR"
sudo install -m 0644 "$GC_PATH/etc/systemd/exordos-mail-tls-renew.timer" "$SYSTEMD_SERVICE_DIR"
for service in postfix postfix@-.service dovecot cyrus-imapd saslauthd rspamd valkey-server redis-server; do
    sudo systemctl disable --now "$service" || true
done

# Install the shared agent config and first-boot bootstrap script.
sudo mkdir -p "$GC_CFG_DIR" "$WORK_DIR"
sudo cp "$GC_PATH/etc/exordos_metapaas/metapaas_mail_agent.conf" "$GC_CFG_DIR/"
sudo cp "$GC_PATH/etc/exordos_metapaas/logging.yaml" "$GC_CFG_DIR/"
sudo install -m 0755 "$GC_PATH/exordos/images/dp_bootstrap.sh" "$BOOTSTRAP_PATH/0100-metapaas-mail-dp-bootstrap.sh"

# Install Python venv
cd "$GC_PATH"
uv sync
source "$VENV_PATH/bin/activate"

sudo ln -sf "$VENV_PATH/bin/exordos-universal-agent" "/usr/bin/exordos-universal-agent"

deactivate

# Install systemd service files
sudo cp "$GC_PATH/etc/systemd/exordos-metapaas-mail-configure.service" $SYSTEMD_SERVICE_DIR
sudo cp "$GC_PATH/etc/systemd/exordos-metapaas-mail-agent.service" $SYSTEMD_SERVICE_DIR

# The base agent, not MailCapabilityDriver, delivers mail.env and invokes its
# configure hook. Order that path too, without modifying the shared base image.
sudo mkdir -p "${SYSTEMD_SERVICE_DIR}exordos-universal-agent.service.d"
sudo cp "$GC_PATH/etc/systemd/exordos-universal-agent.service.d/20-mail-bootstrap.conf" \
    "${SYSTEMD_SERVICE_DIR}exordos-universal-agent.service.d/20-mail-bootstrap.conf"

# Keep the agent enabled for recovery; its unit waits for bootstrap to finish.
# Mail configuration fails visibly if persistent log mounts are unavailable.
sudo systemctl enable exordos-metapaas-mail-agent
