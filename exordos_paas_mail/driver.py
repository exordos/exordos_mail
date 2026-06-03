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


def _reload_dovecot() -> None:
    try:
        subprocess.run(["doveadm", "reload"], check=True, timeout=10)
        LOG.info("Dovecot reloaded")
    except Exception:
        LOG.warning("Failed to reload dovecot; attempting restart", exc_info=True)
        subprocess.run(["systemctl", "restart", "dovecot"], timeout=30)


def _reload_postfix() -> None:
    try:
        subprocess.run(["postfix", "reload"], check=True, timeout=10)
        LOG.info("Postfix reloaded")
    except Exception:
        LOG.warning("Failed to reload postfix; attempting restart", exc_info=True)
        subprocess.run(["systemctl", "restart", "postfix"], timeout=30)


def _postmap(path: str) -> None:
    try:
        subprocess.run(["postmap", path], check=True, timeout=30)
    except Exception:
        LOG.error("postmap %s failed", path, exc_info=True)
        raise


class MailInstance(meta.MetaDataPlaneModel):
    """Data plane model for a single mail (Postfix + Dovecot) node.

    Reconciles target state (from control plane) with actual state on the
    local mail server by managing the Dovecot passwd-file and Postfix
    virtual mailbox map.
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

    # -- Dovecot passwd-file format --
    # username:password_hash:uid:gid:gecos:home:shell:extra_fields
    # Quota rule goes in the extra_fields section.

    def _build_users_file(self) -> str:
        lines = []
        for username, info in self.accounts.items():
            password_hash = info.get("password_hash", "")
            active = info.get("active", True)
            quota_mb = info.get("quota_mb", 0)

            if not active:
                continue

            home = f"/var/mail/{self.domain}/{username}"
            extra = ""
            if quota_mb > 0:
                extra = f"userdb_quota_rule=*:storage={quota_mb}M"

            lines.append(
                f"{username}@{self.domain}:{password_hash}:1001:1001::{home}::{extra}"
            )
        return "\n".join(lines) + "\n" if lines else ""

    def _build_vmailbox_file(self) -> str:
        lines = []
        for username, info in self.accounts.items():
            if not info.get("active", True):
                continue
            lines.append(f"{username}@{self.domain}  {self.domain}/{username}/")
        return "\n".join(lines) + "\n" if lines else ""

    def _read_users_file(self) -> dict:
        result = {}
        try:
            with open(constants.MAIL_USERS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(":")
                    if len(parts) >= 2:
                        full_addr = parts[0]
                        result[full_addr] = line
        except FileNotFoundError:
            pass
        return result

    # -- MetaDataPlaneModel interface --

    def dump_to_dp(self) -> None:
        users_content = self._build_users_file()
        vmailbox_content = self._build_vmailbox_file()

        users_changed = _write_file_atomic(constants.MAIL_USERS_FILE, users_content)
        vmailbox_changed = _write_file_atomic(
            constants.MAIL_VMAILBOX_FILE, vmailbox_content
        )

        if vmailbox_changed:
            _postmap(constants.MAIL_VMAILBOX_FILE)
            _reload_postfix()

        if users_changed:
            _reload_dovecot()

    def restore_from_dp(self) -> None:
        actual = self._read_users_file()
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
        # Instance exists along with the VM — nothing to delete here
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
