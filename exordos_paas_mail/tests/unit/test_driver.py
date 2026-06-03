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

import exordos_paas_mail.driver as drv_module


class _Stub:
    """Plain object that exposes the driver's file-building methods."""

    def __init__(self, domain, accounts):
        self.domain = domain
        self.accounts = accounts

    _build_users_file = drv_module.MailInstance._build_users_file
    _build_vmailbox_file = drv_module.MailInstance._build_vmailbox_file


class TestMailInstanceUsersFile:
    def _make_instance(self, domain, accounts):
        return _Stub(domain, accounts)

    def test_empty_accounts(self) -> None:
        inst = self._make_instance("example.com", {})
        assert inst._build_users_file() == ""

    def test_single_active_account(self) -> None:
        inst = self._make_instance(
            "example.com",
            {
                "alice": {
                    "password_hash": "{SHA512-CRYPT}$6$abc",
                    "active": True,
                    "quota_mb": 0,
                }
            },
        )
        content = inst._build_users_file()
        assert "alice@example.com" in content
        assert "{SHA512-CRYPT}$6$abc" in content

    def test_inactive_account_excluded(self) -> None:
        inst = self._make_instance(
            "example.com",
            {
                "bob": {
                    "password_hash": "{SHA512-CRYPT}$6$xyz",
                    "active": False,
                    "quota_mb": 0,
                }
            },
        )
        content = inst._build_users_file()
        assert "bob@example.com" not in content

    def test_quota_included(self) -> None:
        inst = self._make_instance(
            "example.com",
            {
                "carol": {
                    "password_hash": "{SHA512-CRYPT}$6$qrs",
                    "active": True,
                    "quota_mb": 512,
                }
            },
        )
        content = inst._build_users_file()
        assert "storage=512M" in content

    def test_vmailbox_active_only(self) -> None:
        inst = self._make_instance(
            "example.com",
            {
                "dave": {"password_hash": "x", "active": True, "quota_mb": 0},
                "eve": {"password_hash": "x", "active": False, "quota_mb": 0},
            },
        )
        vmailbox = inst._build_vmailbox_file()
        assert "dave@example.com" in vmailbox
        assert "eve@example.com" not in vmailbox
