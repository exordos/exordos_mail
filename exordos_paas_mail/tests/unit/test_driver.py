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

import exordos_paas_mail.driver as drv_module


class _Stub:
    """Plain object exposing MailInstance's file-building methods."""

    def __init__(self, domain, accounts):
        self.domain = domain
        self.accounts = accounts

    _build_exim4_passwd = drv_module.MailInstance._build_exim4_passwd
    _build_users_file = drv_module.MailInstance._build_users_file


class TestExim4Passwd:
    def _make(self, domain, accounts):
        return _Stub(domain, accounts)

    def test_empty_accounts(self) -> None:
        inst = self._make("example.com", {})
        assert inst._build_exim4_passwd() == ""

    def test_active_account(self) -> None:
        inst = self._make(
            "example.com",
            {"alice": {"password_hash": "{SHA512-CRYPT}$6$abc", "active": True, "quota_mb": 0}},
        )
        passwd = inst._build_exim4_passwd()
        assert "alice@example.com:{SHA512-CRYPT}$6$abc" in passwd

    def test_inactive_excluded(self) -> None:
        inst = self._make(
            "example.com",
            {"bob": {"password_hash": "hash", "active": False, "quota_mb": 0}},
        )
        assert "bob@example.com" not in inst._build_exim4_passwd()

    def test_multiple_accounts(self) -> None:
        inst = self._make(
            "example.com",
            {
                "alice": {"password_hash": "ha", "active": True, "quota_mb": 0},
                "bob": {"password_hash": "hb", "active": True, "quota_mb": 0},
            },
        )
        passwd = inst._build_exim4_passwd()
        assert "alice@example.com:ha" in passwd
        assert "bob@example.com:hb" in passwd


class TestDovecotUsersFile:
    def _make(self, domain, accounts):
        return _Stub(domain, accounts)

    def test_empty(self) -> None:
        inst = self._make("example.com", {})
        assert inst._build_users_file() == ""

    def test_active_with_quota(self) -> None:
        inst = self._make(
            "example.com",
            {"carol": {"password_hash": "{SHA512-CRYPT}$6$qrs", "active": True, "quota_mb": 512}},
        )
        line = inst._build_users_file()
        assert "carol@example.com" in line
        assert "storage=512M" in line

    def test_inactive_excluded(self) -> None:
        inst = self._make(
            "example.com",
            {"dave": {"password_hash": "h", "active": False, "quota_mb": 0}},
        )
        assert "dave@example.com" not in inst._build_users_file()

    def test_home_path(self) -> None:
        inst = self._make(
            "test.local",
            {"eve": {"password_hash": "h", "active": True, "quota_mb": 0}},
        )
        assert "/var/mail/test.local/eve" in inst._build_users_file()
