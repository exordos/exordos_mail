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

DEV_SDK_PATH="/opt/gcl_sdk"
SDK_DEV_MODE=$([ -d "$DEV_SDK_PATH" ] && echo "true" || echo "false")

# Install system packages
sudo apt update
sudo apt dist-upgrade -y
sudo apt install -y \
    postfix dovecot-core dovecot-imapd dovecot-pop3d \
    spamassassin clamav clamav-daemon \
    libev-dev

# Create Postfix vmail user for virtual mailboxes
if ! id vmail &>/dev/null; then
    sudo groupadd -g 1001 vmail
    sudo useradd -u 1001 -g vmail -m -d /var/mail vmail
fi

# Create directories
sudo mkdir -p $GC_CFG_DIR
sudo mkdir -p $WORK_DIR
sudo mkdir -p /var/mail

# Configure Postfix for virtual mailboxes (template; configured by bootstrap)
sudo postconf -e "myhostname = mail.local"
sudo postconf -e "mydestination = localhost"
sudo postconf -e "virtual_mailbox_base = /var/mail"
sudo postconf -e "virtual_mailbox_maps = hash:/etc/postfix/vmailbox"
sudo postconf -e "virtual_minimum_uid = 1001"
sudo postconf -e "virtual_uid_maps = static:1001"
sudo postconf -e "virtual_gid_maps = static:1001"
touch /etc/postfix/vmailbox
sudo postmap /etc/postfix/vmailbox

# Configure Dovecot to use passwd-file for auth
sudo tee /etc/dovecot/conf.d/10-auth.conf > /dev/null <<'EOF'
auth_mechanisms = plain login
!include auth-passwdfile.conf.ext
EOF

sudo tee /etc/dovecot/conf.d/auth-passwdfile.conf.ext > /dev/null <<'EOF'
passdb {
  driver = passwd-file
  args = scheme=SHA512-CRYPT /etc/exordos_metapaas/mail.users
}
userdb {
  driver = passwd-file
  args = /etc/exordos_metapaas/mail.users
  default_fields = uid=vmail gid=vmail home=/var/mail/%d/%n
}
EOF

# Empty users file so Dovecot starts cleanly
sudo touch $GC_CFG_DIR/mail.users
sudo chown root:root $GC_CFG_DIR/mail.users
sudo chmod 0640 $GC_CFG_DIR/mail.users

# Disable mail services until configured by bootstrap
sudo systemctl disable postfix dovecot || true

# Install agent config + bootstrap
sudo cp "$GC_PATH/etc/exordos_metapaas/metapaas_mail_agent.conf" $GC_CFG_DIR/
sudo cp "$GC_PATH/etc/exordos_metapaas/logging.yaml" $GC_CFG_DIR/
sudo cp "$GC_PATH/exordos/images/dp_bootstrap.sh" $BOOTSTRAP_PATH/0100-metapaas-mail-dp-bootstrap.sh
sudo chmod +x $BOOTSTRAP_PATH/0100-metapaas-mail-dp-bootstrap.sh

cd "$GC_PATH"
uv sync
source "$GC_PATH/.venv/bin/activate"

# In the dev mode the gcl_sdk package is installed from the local machine
if [[ "$SDK_DEV_MODE" == "true" ]]; then
    uv pip uninstall -y gcl_sdk
    uv pip install -e "$DEV_SDK_PATH"
fi

# Link the universal agent (loads the MailCapabilityDriver via entry point)
sudo ln -sf "$VENV_PATH/bin/exordos-universal-agent" "/usr/bin/exordos-universal-agent"

deactivate

# Install the mail configure script
sudo tee /usr/local/bin/exordos-mail-configure > /dev/null <<'CONFIGURE_SCRIPT'
#!/usr/bin/env bash
# Configure Postfix and Dovecot from /etc/exordos_metapaas/mail.env
set -eu

source /etc/exordos_metapaas/mail.env

# Configure Postfix for the instance domain
postconf -e "myhostname = mail.${MAIL_DOMAIN}"
postconf -e "mydomain = ${MAIL_DOMAIN}"
postconf -e "myorigin = \$mydomain"
postconf -e "virtual_mailbox_domains = ${MAIL_DOMAIN}"

# Set postmaster password (create system account for local delivery)
echo "postmaster:${MAIL_ROOT_PASSWORD}" | chpasswd

# Ensure vmail directories exist
mkdir -p "/var/mail/${MAIL_DOMAIN}"
chown -R vmail:vmail /var/mail/

# Enable and start mail services
systemctl enable postfix dovecot
systemctl restart postfix dovecot

echo "Mail server configured for domain: ${MAIL_DOMAIN}"
CONFIGURE_SCRIPT
sudo chmod +x /usr/local/bin/exordos-mail-configure

# Install systemd service files
sudo cp "$GC_PATH/etc/systemd/exordos-metapaas-mail-configure.service" $SYSTEMD_SERVICE_DIR
sudo cp "$GC_PATH/etc/systemd/exordos-metapaas-mail-agent.service" $SYSTEMD_SERVICE_DIR

# Enable the dataplane agent (mail services are enabled by bootstrap after
# the config is delivered by the control plane)
sudo systemctl enable exordos-metapaas-mail-agent
