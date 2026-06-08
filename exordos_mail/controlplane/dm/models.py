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

from restalchemy.dm import filters as dm_filters
from restalchemy.dm import models
from restalchemy.dm import properties
from restalchemy.dm import relationships
from restalchemy.dm import types
from restalchemy.storage.sql import orm
from gcl_sdk.agents.universal.dm import models as ua_models

from exordos_mail import utils as u


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

    def insert(self, session=None):
        super().insert(session=session)
        self._touch_parent(session=session)

    def update(self, session=None, force=False):
        super().update(session=session, force=force)
        self._touch_parent(session=session)

    def delete(self, session=None, **kwargs):
        res = super().delete(session=session, **kwargs)
        self._touch_parent(session=session)
        return res
