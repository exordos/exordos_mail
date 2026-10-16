#    Copyright 2026 Genesis Corporation.
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import uuid

import pytest
from exordos_metapaas.common import audit

from exordos_mail.controlplane.dm import models


@pytest.mark.parametrize(
    "model", [models.MailVersion, models.MailInstance, models.MailAccount]
)
def test_models_record_mail_events(model: type) -> None:
    assert issubclass(model, audit.AuditLogSQLStorableMixin)
    assert model.get_audit_service_name() == "mail"
    assert model.get_audit_resource_type() == model.__tablename__


def test_account_snapshot_omits_credentials() -> None:
    parent = models.MailInstance(
        name="mail",
        domain="example.com",
        cpu=1,
        ram=512,
        disk_size=8,
        project_id=uuid.uuid4(),
        version=models.MailVersion(name="v", image="image"),
    )
    account = models.MailAccount(
        name="user",
        username="user",
        instance=parent,
        project_id=parent.project_id,
        password="password-canary",
        password_hash="hash-canary",
    )
    snapshot = account.dump_to_audit_snapshot()
    assert {"password", "password_hash"}.isdisjoint(snapshot)
    assert snapshot["instance"] == str(parent.uuid)
    assert snapshot["username"] == "user"
