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

import uuid

from passlib.hash import sha512_crypt

from exordos_mail.controlplane.dm import models


def _account(password, password_hash=""):
    version = models.MailVersion(
        uuid=uuid.uuid4(), name="exim4_1", image="http://repo/img"
    )
    instance = models.MailInstance(
        uuid=uuid.uuid4(),
        name="m",
        domain="ex.com",
        project_id=uuid.uuid4(),
        cpu=1,
        ram=1024,
        disk_size=10,
        version=version,
    )
    return models.MailAccount(
        uuid=uuid.uuid4(),
        project_id=uuid.uuid4(),
        instance=instance,
        username="smtp",
        password=password,
        password_hash=password_hash,
    )


class TestMailVersion:
    def test_tablename(self) -> None:
        assert models.MailVersion.__tablename__ == "mail_versions"


class TestMailInstance:
    def test_tablename(self) -> None:
        assert models.MailInstance.__tablename__ == "mail_instances"

    def test_status_values(self) -> None:
        values = [s.value for s in models.MailStatus]
        assert "NEW" in values
        assert "IN_PROGRESS" in values
        assert "ACTIVE" in values
        assert "ERROR" in values


class TestMailAccount:
    def test_tablename(self) -> None:
        assert models.MailAccount.__tablename__ == "mail_accounts"

    def test_derive_hash_from_plaintext(self) -> None:
        acc = _account("s3cret")
        acc._derive_hash()
        assert acc.password == "s3cret"
        assert acc.password_hash.startswith("$6$")
        assert sha512_crypt.verify("s3cret", acc.password_hash)

    def test_derive_hash_idempotent_when_unchanged(self) -> None:
        # An unchanged password must keep the same salted hash so the data
        # plane is not needlessly reprovisioned (and the EM does not re-apply).
        acc = _account("s3cret", password_hash=sha512_crypt.hash("s3cret"))
        # Simulate a load: the property is no longer dirty.
        acc.properties["password"].set_value_force("s3cret")
        original = acc.password_hash
        acc._derive_hash()
        assert acc.password_hash == original

    def test_already_hashed_used_verbatim(self) -> None:
        stored = sha512_crypt.hash("s3cret")
        acc = _account(stored)
        acc._derive_hash()
        assert acc.password_hash == stored

    def test_password_hash_excluded_from_em_resource(self) -> None:
        acc = _account("s3cret")
        assert "password_hash" in acc.get_resource_ignore_fields()
