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

import enum

from gcl_sdk.agents.universal.dm import models as ua_models
from passlib.hash import sha512_crypt as _sha512_crypt
from restalchemy.dm import filters as dm_filters
from restalchemy.dm import models, properties, relationships, types
from restalchemy.storage.sql import orm

from exordos_mail import utils as u


def _is_crypt_hash(value: str) -> bool:
    """Return True if value is already a crypt hash or has a Dovecot-style prefix."""
    return value.startswith("$") or (value.startswith("{") and "}" in value)


class MailStatus(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"


class MailVersion(
    models.ModelWithUUID,
    models.ModelWithNameDesc,
    models.ModelWithTimestamp,
    orm.SQLStorableMixin,
    ua_models.TargetResourceMixin,
):
    __tablename__ = "mail_versions"

    image = properties.property(types.String(max_length=2048))


class MailInstance(
    models.ModelWithUUID,
    models.ModelWithNameDesc,
    models.ModelWithProject,
    models.ModelWithTimestamp,
    orm.SQLStorableMixin,
):
    __tablename__ = "mail_instances"

    name = properties.property(types.String(min_length=1, max_length=255))
    domain = properties.property(
        types.String(min_length=1, max_length=255), required=True
    )
    status = properties.property(
        types.Enum([status.value for status in MailStatus]),
        default=MailStatus.NEW.value,
    )
    ipsv4 = properties.property(
        types.TypedList(types.String(max_length=15)),
        default=lambda: [],
    )
    cpu = properties.property(types.Integer(min_value=1, max_value=128))
    ram = properties.property(types.Integer(min_value=512, max_value=1024**3))
    disk_size = properties.property(types.Integer(min_value=8, max_value=1024**3))
    version = relationships.relationship(MailVersion, required=True, read_only=True)
    # DKIM public key reported back from the data plane — publish it in DNS at
    # <dkim_selector>._domainkey.<domain>. Populated by the paas builder once
    # the configure script has generated the key on the node.
    dkim_public_key = properties.property(types.String(max_length=4096), default="")
    dkim_selector = properties.property(types.String(max_length=255), default="")

    def get_accounts(self, session=None):
        return MailAccount.objects.get_all(
            session=session, filters={"instance": dm_filters.EQ(self)}
        )

    def _validate_update(self, session=None):
        disk_size = self.properties["disk_size"]
        if disk_size.is_dirty() and disk_size.old_value > self.disk_size:
            raise ValueError("disk_size shrink is not supported yet")

    def update(self, session=None, force=False):
        self._validate_update(session=session)
        super().update(session=session, force=force)

    def delete(self, session=None, **kwargs):
        u.remove_nested_dm(MailAccount, "instance", self, session=session)
        return super().delete(session=session, **kwargs)


class MailAccount(
    models.ModelWithUUID,
    models.ModelWithNameDesc,
    models.ModelWithTimestamp,
    models.ModelWithProject,
    ua_models.TargetResourceMixin,
    orm.SQLStorableMixin,
):
    __tablename__ = "mail_accounts"

    instance = relationships.relationship(MailInstance, required=True, read_only=True)
    username = properties.property(
        types.String(min_length=1, max_length=255), required=True, read_only=True
    )
    # Plaintext password (write-only in the API). It is stored verbatim so the
    # EM target reconciles idempotently: the manifest always sends the same
    # plaintext, so target == actual. The salted crypt hash below can never
    # match a plaintext manifest value, which is what used to spin the builders.
    password = properties.property(
        types.String(min_length=1, max_length=1024), required=True
    )
    # exim4 crypt hash derived from `password` and pushed to the data plane.
    # Kept out of the EM resource (see get_resource_ignore_fields) because its
    # random salt would otherwise make the actual never match the target.
    password_hash = properties.property(types.String(max_length=1024), default="")
    active = properties.property(types.Boolean(), default=True)

    def get_resource_ignore_fields(self):
        # password_hash is a derived, per-save salted value; excluding it keeps
        # the account's EM resource stable so the db-back agent stops re-applying.
        return {"password_hash"}

    def _touch_parent(self, session=None):
        self.instance.update(force=True)

    def _derive_hash(self):
        # Recompute the crypt hash only when the plaintext changed (or is
        # missing), so an unchanged re-apply keeps the same salted hash and does
        # not needlessly reprovision the data plane. An already-hashed value
        # (e.g. backfilled from the old password_hash column) is used verbatim.
        if not self.properties["password"].is_dirty() and self.password_hash:
            return
        pw = self.password
        self.password_hash = pw if _is_crypt_hash(pw) else _sha512_crypt.hash(pw)

    def insert(self, session=None):
        self._derive_hash()
        super().insert(session=session)
        self._touch_parent(session=session)

    def update(self, session=None, force=False):
        self._derive_hash()
        # Only touch the parent when the account actually changed. The core
        # agent re-applies the account target every cycle; when nothing changed
        # the update is a no-op, so an unconditional force-touch would keep
        # bumping the instance's updated_at and spin the mail_instance /
        # mail_instance_iaas builders.
        changed = self.is_dirty() or force
        super().update(session=session, force=force)
        if changed:
            self._touch_parent(session=session)

    def delete(self, session=None, **kwargs):
        res = super().delete(session=session, **kwargs)
        self._touch_parent(session=session)
        return res
