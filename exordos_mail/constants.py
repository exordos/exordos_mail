#    Copyright 2026 Genesis Corporation.
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

# Path on the dataplane (mail) node where the control plane delivers the
# mail environment config (must match the configure service's EnvironmentFile).
MAIL_ENV_FILE = "/etc/exordos_metapaas/mail.env"

# Path to the exim4 passwd file managed by the DP agent (SMTP auth).
# Format: username@domain:password_hash  (crypteq-compatible, SHA512-CRYPT)
EXIM4_PASSWD_FILE = "/etc/exim4/passwd"

# DKIM selector used by the configure script (opendkim-genkey -s platform).
DKIM_SELECTOR = "platform"

# Path to the DKIM public key record generated on the dataplane by the
# configure script. The file holds the DNS TXT record (split into quoted
# chunks) that must be published at <selector>._domainkey.<domain>.
EXIM4_DKIM_TXT_FILE = f"/etc/exim4/dkim/{DKIM_SELECTOR}.txt"
