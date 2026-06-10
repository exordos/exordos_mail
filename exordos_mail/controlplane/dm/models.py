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
    password_hash = properties.property(
        types.String(min_length=1, max_length=1024), required=True
    )
    active = properties.property(types.Boolean(), default=True)

    def _touch_parent(self, session=None):
        self.instance.update(force=True)

    def _maybe_hash_password(self):
        if self.password_hash and not _is_crypt_hash(self.password_hash):
            # If the plaintext matches the already-stored crypt hash (e.g. the
            # core-agent re-applies the same plaintext target every cycle), keep
            # the existing hash to avoid generating a new random salt on every
            # update and triggering a needless DP re-provision.
            old_hash = self.properties["password_hash"].old_value
            if (
                old_hash
                and _is_crypt_hash(old_hash)
                and _sha512_crypt.verify(self.password_hash, old_hash)
            ):
                self.password_hash = old_hash
            else:
                self.password_hash = _sha512_crypt.hash(self.password_hash)

    def insert(self, session=None):
        self._maybe_hash_password()
        super().insert(session=session)
        self._touch_parent(session=session)

    def update(self, session=None, force=False):
        self._maybe_hash_password()
        super().update(session=session, force=force)
        self._touch_parent(session=session)

    def delete(self, session=None, **kwargs):
        res = super().delete(session=session, **kwargs)
        self._touch_parent(session=session)
        return res
