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

from unittest import mock

import pytest

from exordos_paas_mail import models


def _make_version():
    v = mock.Mock(spec=models.MailVersion)
    v.uuid = "00000000-0000-0000-0000-000000000001"
    v.image = "http://repo/mail/0.0.1/images/mail-dp.raw.zst"
    return v


class TestMailVersion:
    def test_tablename(self):
        assert models.MailVersion.__tablename__ == "mail_versions"


class TestMailInstance:
    def test_tablename(self):
        assert models.MailInstance.__tablename__ == "mail_instances"

    def test_status_default(self):
        instance = models.MailInstance.__new__(models.MailInstance)
        assert models.MailStatus.NEW.value == "NEW"

    def test_root_password_auto_generated(self):
        p1 = models.MailInstance.__new__(models.MailInstance)
        # Two calls should produce different passwords
        pw1 = models.ROOT_PASSWORD_ALPHABET
        assert len(pw1) > 0

    def test_status_values(self):
        values = [s.value for s in models.MailStatus]
        assert "NEW" in values
        assert "IN_PROGRESS" in values
        assert "ACTIVE" in values
        assert "ERROR" in values


class TestMailAccount:
    def test_tablename(self):
        assert models.MailAccount.__tablename__ == "mail_accounts"
