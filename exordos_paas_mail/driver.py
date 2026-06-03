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
from __future__ import annotations

import logging
import os
import subprocess

from gcl_sdk.agents.universal import constants as c
from gcl_sdk.agents.universal.drivers import meta
from gcl_sdk.infra import constants as pc
from restalchemy.dm import properties
from restalchemy.dm import types as ra_types

from exordos_paas_mail import constants

LOG = logging.getLogger(__name__)


def _write_file_atomic(path: str, content: str) -> bool:
    """Write file; return True if content changed."""
    try:
        with open(path, "r") as f:
            existing = f.read()
        if existing == content:
            return False
    except FileNotFoundError:
        pass

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.rename(tmp, path)
    return True


def _reload_exim4() -> None:
    try:
        subprocess.run(["exim4", "-DEXIM_OUTPUT_FILTER", "-qff"], check=False, timeout=5)
        subprocess.run(["systemctl", "reload", "exim4"], check=True, timeout=10)
        LOG.info("exim4 reloaded")
    except Exception:
        LOG.warning("Failed to reload exim4; attempting restart", exc_info=True)
        subprocess.run(["systemctl", "restart", "exim4"], timeout=30)


def _reload_dovecot() -> None:
    try:
        subprocess.run(["doveadm", "reload"], check=True, timeout=10)
        LOG.info("Dovecot reloaded")
    except Exception:
        LOG.warning("Failed to reload dovecot; attempting restart", exc_info=True)
        subprocess.run(["systemctl", "restart", "dovecot"], timeout=30)


class MailInstance(meta.MetaDataPlaneModel):
    """Data plane model for a single mail (exim4 + Dovecot) node.

    Reconciles target account state (from control plane) with the local
    mail server by managing two files in sync:
      - /etc/exim4/passwd  — exim4 SMTP auth (lsearch format, SHA512-CRYPT)
      - /etc/exordos_metapaas/mail.users — Dovecot passwd-file (IMAP/POP3)
    """

    name = properties.property(
        ra_types.String(min_length=1, max_length=512),
        required=True,
    )
    domain = properties.property(
        ra_types.String(min_length=1, max_length=255),
        required=True,
    )
    accounts = properties.property(ra_types.Dict(), default=dict)
    status = properties.property(
        ra_types.Enum([s.value for s in pc.InstanceStatus]),
        default=pc.InstanceStatus.ACTIVE.value,
    )

    _meta_fields = {"uuid", "name", "domain"}

    def get_meta_model_fields(self) -> set[str] | None:
        return self._meta_fields

    # ------------------------------------------------------------------
    # exim4 passwd file  (SMTP AUTH — lsearch lookup by username@domain)
    # Format: username@domain:password_hash
    # The auth config uses crypteq which understands {SHA512-CRYPT}$6$...
    # ------------------------------------------------------------------

    def _build_exim4_passwd(self) -> str:
        lines = []
        for username, info in self.accounts.items():
            if not info.get("active", True):
                continue
            password_hash = info.get("password_hash", "")
            lines.append(f"{username}@{self.domain}:{password_hash}")
        return "\n".join(lines) + "\n" if lines else ""

    # ------------------------------------------------------------------
    # Dovecot passwd-file  (IMAP/POP3 auth + userdb)
    # Format: username@domain:hash:uid:gid:gecos:home:shell::extra
    # Quota goes in the extra_fields section.
    # ------------------------------------------------------------------

    def _build_users_file(self) -> str:
        lines = []
        for username, info in self.accounts.items():
            if not info.get("active", True):
                continue
            password_hash = info.get("password_hash", "")
            quota_mb = info.get("quota_mb", 0)
            home = f"/var/mail/{self.domain}/{username}"
            extra = f"userdb_quota_rule=*:storage={quota_mb}M" if quota_mb > 0 else ""
            lines.append(
                f"{username}@{self.domain}:{password_hash}:1001:1001::{home}::{extra}"
            )
        return "\n".join(lines) + "\n" if lines else ""

    def _read_exim4_passwd(self) -> dict:
        result = {}
        try:
            with open(constants.EXIM4_PASSWD_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(":")
                    if len(parts) >= 1:
                        result[parts[0]] = line
        except FileNotFoundError:
            pass
        return result

    # -- MetaDataPlaneModel interface --

    def dump_to_dp(self) -> None:
        exim4_changed = _write_file_atomic(
            constants.EXIM4_PASSWD_FILE, self._build_exim4_passwd()
        )
        dovecot_changed = _write_file_atomic(
            constants.MAIL_USERS_FILE, self._build_users_file()
        )

        if exim4_changed:
            _reload_exim4()

        if dovecot_changed:
            _reload_dovecot()

    def restore_from_dp(self) -> None:
        actual = self._read_exim4_passwd()
        self.accounts = {}
        for full_addr in actual:
            if "@" in full_addr:
                local = full_addr.split("@")[0]
                self.accounts[local] = {
                    "password_hash": "",
                    "active": True,
                    "quota_mb": 0,
                }

    def delete_from_dp(self) -> None:
        pass

    def update_on_dp(self) -> None:
        self.dump_to_dp()


class MailCapabilityDriver(meta.MetaFileStorageAgentDriver):
    """Mail capability driver for the universal agent."""

    MAIL_META_PATH = os.path.join(c.WORK_DIR, "mail_meta.json")

    __model_map__ = {
        "mail_instance_node": MailInstance,
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, meta_file=self.MAIL_META_PATH, **kwargs)
