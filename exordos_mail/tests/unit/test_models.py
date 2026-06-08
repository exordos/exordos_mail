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

from exordos_mail.controlplane.dm import models


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
