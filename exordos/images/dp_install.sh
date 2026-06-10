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


# Install mail packages — exim4 only (SMTP relay, like genesis_sender; no IMAP)
sudo apt update
sudo apt dist-upgrade -y
sudo apt install -y \
    exim4 opendkim-tools swaks whois \
    libev-dev

# Create directories
sudo mkdir -p $GC_CFG_DIR
sudo mkdir -p $WORK_DIR
sudo mkdir -p /var/log/exim4
sudo chown Debian-exim:Debian-exim /var/log/exim4
sudo chmod 770 /var/log/exim4

# Pre-configure exim4 split config (domain and TLS set by configure script)
sudo debconf-set-selections <<'DEBCONF'
exim4-config exim4/dc_eximconfig_configtype select internet site
exim4-config exim4/dc_use_split_config boolean true
DEBCONF
sudo dpkg-reconfigure -f noninteractive exim4-config || true

# Prepare empty exim4 passwd file (populated by agent when accounts are pushed)
sudo touch /etc/exim4/passwd
sudo chown root:Debian-exim /etc/exim4/passwd
sudo chmod 640 /etc/exim4/passwd

# Pre-install exim4 platform config stubs (overwritten by configure script)
sudo mkdir -p /etc/exim4/conf.d/main /etc/exim4/conf.d/auth /etc/exim4/conf.d/transport
sudo touch /etc/exim4/conf.d/main/01_platform
sudo touch /etc/exim4/conf.d/auth/01_platform
sudo touch /etc/exim4/conf.d/transport/01_platform

# Disable exim4 until configure script runs on first-boot (after mail.env delivery)
sudo systemctl disable exim4 || true

# Install agent config + first-boot bootstrap script
sudo cp "$GC_PATH/etc/exordos_metapaas/metapaas_mail_agent.conf" $GC_CFG_DIR/
sudo cp "$GC_PATH/etc/exordos_metapaas/logging.yaml" $GC_CFG_DIR/
sudo cp "$GC_PATH/exordos/images/dp_bootstrap.sh" $BOOTSTRAP_PATH/0100-metapaas-mail-dp-bootstrap.sh
sudo chmod +x $BOOTSTRAP_PATH/0100-metapaas-mail-dp-bootstrap.sh

# Install configure script — exim4 only (genesis_sender pattern, no IMAP)
sudo tee /usr/local/bin/exordos-mail-configure > /dev/null <<'CONFIGURE_SCRIPT'
#!/usr/bin/env bash
# Configure exim4 from /etc/exordos_metapaas/mail.env (genesis_sender pattern).
set -eu
set -o pipefail

source /etc/exordos_metapaas/mail.env

DOMAIN="${MAIL_DOMAIN}"
DKIM_DIR="/etc/exim4/dkim"

# -- hostname --
hostnamectl set-hostname "mail.${DOMAIN}" || true

# -- exim4 main config --
cat > /etc/exim4/update-exim4.conf.conf <<EOF
dc_eximconfig_configtype='internet'
dc_other_hostnames='${DOMAIN}'
dc_local_interfaces='<; [0.0.0.0]:25; [0.0.0.0]:465; [0.0.0.0]:587'
dc_readhost=''
dc_relay_domains=''
dc_minimaldns='false'
dc_smarthost=''
CFILEMODE='644'
dc_use_split_config='true'
dc_hide_mailname=''
dc_mailname_in_oh='true'
dc_localdelivery='mail_spool'
EOF

# -- DKIM (generate once; persists on data disk after first boot) --
mkdir -p "${DKIM_DIR}"
if [[ ! -f "${DKIM_DIR}/platform.private" ]]; then
    opendkim-genkey -D "${DKIM_DIR}/" -d "${DOMAIN}" -s platform
    chown Debian-exim:Debian-exim "${DKIM_DIR}" -R
    chmod 640 "${DKIM_DIR}"/*
fi

cat > /etc/exim4/conf.d/transport/01_platform <<EOF
DKIM_CANON = relaxed
DKIM_DOMAIN = ${DOMAIN}
DKIM_PRIVATE_KEY = ${DKIM_DIR}/platform.private
DKIM_SELECTOR = platform
EOF

# -- TLS (self-signed; generate once) --
if [[ ! -f /etc/exim4/exim.key ]]; then
    openssl req -x509 -sha256 -days 9000 -nodes -newkey rsa:4096 \
        -keyout /etc/exim4/exim.key \
        -out /etc/exim4/exim.crt \
        -subj "/CN=${DOMAIN}/O=${DOMAIN}/C=US"
    chown root:Debian-exim /etc/exim4/exim.key /etc/exim4/exim.crt
    chmod 640 /etc/exim4/exim.key /etc/exim4/exim.crt
fi

echo "MAIN_TLS_ENABLE = true" > /etc/exim4/conf.d/main/01_platform

# -- SMTP AUTH (PLAIN + LOGIN; passwords in /etc/exim4/passwd) --
cat > /etc/exim4/conf.d/auth/01_platform <<'EOF'
plain_server:
  driver = plaintext
  public_name = PLAIN
  server_condition = "${if crypteq{$auth3}{${extract{1}{:}{${lookup{$auth2}lsearch{CONFDIR/passwd}{$value}{*:*}}}}}{1}{0}}"
  server_set_id = $auth2
  server_prompts = :
  .ifndef AUTH_SERVER_ALLOW_NOTLS_PASSWORDS
  server_advertise_condition = ${if eq{$tls_in_cipher}{}{}{*}}
  .endif
login_server:
  driver = plaintext
  public_name = LOGIN
  server_prompts = "Username:: : Password::"
  server_condition = "${if crypteq{$auth2}{${extract{1}{:}{${lookup{$auth1}lsearch{CONFDIR/passwd}{$value}{*:*}}}}}{1}{0}}"
  server_set_id = $auth1
  .ifndef AUTH_SERVER_ALLOW_NOTLS_PASSWORDS
  server_advertise_condition = ${if eq{$tls_in_cipher}{}{}{*}}
  .endif
EOF

update-exim4.conf

# -- Start exim4 --
systemctl enable exim4
systemctl restart exim4

echo "Mail server configured: domain=${DOMAIN}"
echo "DKIM public key: ${DKIM_DIR}/platform.txt"
CONFIGURE_SCRIPT
sudo chmod +x /usr/local/bin/exordos-mail-configure

# Install Python venv
cd "$GC_PATH"
uv sync
source "$VENV_PATH/bin/activate"

sudo ln -sf "$VENV_PATH/bin/exordos-universal-agent" "/usr/bin/exordos-universal-agent"

deactivate

# Install systemd service files
sudo cp "$GC_PATH/etc/systemd/exordos-metapaas-mail-configure.service" $SYSTEMD_SERVICE_DIR
sudo cp "$GC_PATH/etc/systemd/exordos-metapaas-mail-agent.service" $SYSTEMD_SERVICE_DIR

# Enable DP agent (mail services start via configure service after mail.env delivery)
sudo systemctl enable exordos-metapaas-mail-agent
