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

import exordos_mail.dataplane.driver as drv_module


class _Stub:
    """Plain object exposing MailInstance's file-building methods."""

    def __init__(self, domain, accounts):
        self.domain = domain
        self.accounts = accounts

    _build_exim4_passwd = drv_module.MailInstance._build_exim4_passwd
    _strip_dovecot_prefix = staticmethod(drv_module.MailInstance._strip_dovecot_prefix)
    _parse_dkim_txt = staticmethod(drv_module.MailInstance._parse_dkim_txt)


class TestStripDovecotPrefix:
    def test_strips_sha512_crypt(self) -> None:
        assert _Stub._strip_dovecot_prefix("{SHA512-CRYPT}$6$abc") == "$6$abc"

    def test_strips_md5(self) -> None:
        assert _Stub._strip_dovecot_prefix("{MD5}$1$abc") == "$1$abc"

    def test_no_prefix_unchanged(self) -> None:
        assert _Stub._strip_dovecot_prefix("$6$abc") == "$6$abc"

    def test_empty_unchanged(self) -> None:
        assert _Stub._strip_dovecot_prefix("") == ""


class TestExim4Passwd:
    def _make(self, domain, accounts):
        return _Stub(domain, accounts)

    def test_empty_accounts(self) -> None:
        inst = self._make("example.com", {})
        assert inst._build_exim4_passwd() == ""

    def test_active_account_strips_prefix(self) -> None:
        inst = self._make(
            "example.com",
            {"alice": {"password_hash": "{SHA512-CRYPT}$6$abc", "active": True}},
        )
        passwd = inst._build_exim4_passwd()
        assert "alice@example.com:$6$abc" in passwd
        assert "{SHA512-CRYPT}" not in passwd

    def test_raw_hash_unchanged(self) -> None:
        inst = self._make(
            "example.com",
            {"bob": {"password_hash": "$6$salt$hash", "active": True}},
        )
        assert "bob@example.com:$6$salt$hash" in inst._build_exim4_passwd()

    def test_inactive_excluded(self) -> None:
        inst = self._make(
            "example.com",
            {"carol": {"password_hash": "$6$x", "active": False}},
        )
        assert "carol@example.com" not in inst._build_exim4_passwd()

    def test_multiple_accounts(self) -> None:
        inst = self._make(
            "example.com",
            {
                "alice": {"password_hash": "{SHA512-CRYPT}$6$ha", "active": True},
                "bob": {"password_hash": "$6$hb", "active": True},
            },
        )
        passwd = inst._build_exim4_passwd()
        assert "alice@example.com:$6$ha" in passwd
        assert "bob@example.com:$6$hb" in passwd


class TestParseDkimTxt:
    def test_concatenates_quoted_chunks(self) -> None:
        content = (
            'platform._domainkey\tIN\tTXT\t( "v=DKIM1; h=sha256; k=rsa; "\n'
            '\t  "p=MIGfMA0GCSqAB" )  ; ----- DKIM key platform for example.com\n'
        )
        assert _Stub._parse_dkim_txt(content) == (
            "v=DKIM1; h=sha256; k=rsa; p=MIGfMA0GCSqAB"
        )

    def test_single_chunk(self) -> None:
        assert _Stub._parse_dkim_txt('"v=DKIM1; p=ABC"') == "v=DKIM1; p=ABC"

    def test_empty_content(self) -> None:
        assert _Stub._parse_dkim_txt("") == ""
