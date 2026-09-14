#!/usr/bin/env bash

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

set -eu
set -x
set -o pipefail

BOOTSTRAP_LIB=${EXORDOS_BOOTSTRAP_LIB:-/usr/local/lib/exordos/lib_bootstrap.sh}
source "$BOOTSTRAP_LIB"

# Logs live on the persistent disk (survives reboots)
PERSISTENT_DISK=$(find_persistent_disk)
prepare_persistent_disk "$PERSISTENT_DISK" "$PERSISTENT_MOUNT" "xfs"

if [[ -n "$PERSISTENT_DISK" ]]; then
    migrate_to_persistent_restart "/var/log" "${PERSISTENT_MOUNT}/var/log" "systemd-journald rsyslog"
    persist_migrate_complete
fi

# mail-configure is started once the control plane delivers
# /etc/exordos_metapaas/mail.env (ConditionPathExists on the service).
# Queue the start: configure is ordered after this bootstrap unit, so waiting
# synchronously here would deadlock. Mount assertions keep failures visible
# when the agent retries configuration after a failed bootstrap.
sudo systemctl --no-block enable --now exordos-metapaas-mail-configure

echo "Bootstrap completed successfully."
