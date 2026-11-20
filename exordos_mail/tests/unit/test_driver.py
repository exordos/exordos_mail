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

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from gcl_sdk.agents.universal.drivers.exceptions import InvalidDataPlaneObjectError

from exordos_mail.dataplane import driver as drv_module
from exordos_mail.dataplane import mailbox


def test_legacy_empty_mailbox_snapshot_is_reapplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "target.json").write_text('{"accounts": {}, "mailboxes": {}}')
    monkeypatch.setattr(mailbox, "STATE", tmp_path)
    instance = drv_module.MailInstance(
        uuid=uuid4(), name="mail-test", domain="example.test", mode="mailbox"
    )

    with pytest.raises(InvalidDataPlaneObjectError):
        instance.restore_from_dp()


def test_calendar_submission_limits_senders_to_active_mailboxes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "control"
    state.mkdir()
    (state / "provision.hash").write_text("$6$fixture")
    (tmp_path / "tx").mkdir()
    (tmp_path / "tx/scheduler.hash").write_text("$6$scheduler")
    monkeypatch.setattr(mailbox, "STATE", state)
    monkeypatch.setattr(mailbox, "_ensure_inboxes", lambda _: None)
    monkeypatch.setattr(mailbox.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=-1))
    monkeypatch.setattr(mailbox.os, "fchown", lambda *_: None)

    def postmap(args: list[str], **_kwargs) -> None:
        Path(f"{args[1].removeprefix('hash:')}.db").touch()

    monkeypatch.setattr(mailbox.subprocess, "run", postmap)
    mailbox.apply(
        "example.test",
        {"notifier": {"active": True, "password_hash": "$6$fixture"}},
        {
            "alice": {
                "active": True,
                "aliases": ["support"],
                "password_hash": "$6$fixture",
            },
            "bob": {"active": False, "aliases": [], "password_hash": "$6$fixture"},
        },
    )

    assert (
        "calendar-scheduler:alice@example.test : support@example.test"
        in (state / "senders").read_text().splitlines()
    )


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


def test_unified_agent_applies_only_the_configured_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "mode"
    marker.write_text("mailbox")
    monkeypatch.setattr(drv_module, "CONFIGURE_SCRIPT", marker)
    monkeypatch.setattr(drv_module, "MODE_FILE", marker)
    monkeypatch.setattr(drv_module, "CONFIGURE_LOCK", tmp_path / "lock")
    monkeypatch.setattr(mailbox, "STATE", tmp_path)
    env = tmp_path / "mail.env"
    env.write_text("MAIL_MODE=mailbox\n")
    monkeypatch.setattr(drv_module.constants, "MAIL_ENV_FILE", str(env))
    instance = drv_module.MailInstance(
        uuid=uuid4(),
        name="mail-test",
        domain="example.test",
        accounts={"sender": {"password_hash": "$6$fixture", "active": True}},
    )

    with pytest.raises(InvalidDataPlaneObjectError):
        instance.dump_to_dp()
    assert not (tmp_path / "tx.passwd").exists()

    marker.write_text("smtp_only")
    monkeypatch.setattr(mailbox.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=-1))
    monkeypatch.setattr(mailbox.os, "fchown", lambda *_: None)
    monkeypatch.setattr(
        drv_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="active\n" * 3),
    )
    public_key = "v=DKIM1; k=rsa; p=fixture"
    monkeypatch.setattr(
        drv_module.MailInstance, "_read_dkim_public_key", lambda self: public_key
    )
    instance.dump_to_dp()
    assert (tmp_path / "tx.passwd").read_text() == "sender@example.test:$6$fixture\n"
    assert instance.to_ua_resource("mail_instance_node").value["dkim_public_key"] == (
        public_key
    )
    instance.restore_from_dp()
    assert instance.status == "ACTIVE"

    (tmp_path / "tx.passwd").unlink()
    with pytest.raises(InvalidDataPlaneObjectError):
        instance.restore_from_dp()


def test_mailbox_rx_starts_after_applying_recipients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "mode"
    marker.write_text("mailbox")
    monkeypatch.setattr(drv_module, "CONFIGURE_SCRIPT", marker)
    monkeypatch.setattr(drv_module, "MODE_FILE", marker)
    monkeypatch.setattr(drv_module, "CONFIGURE_LOCK", tmp_path / "lock")
    monkeypatch.setattr(mailbox, "STATE", tmp_path)
    monkeypatch.setattr(
        mailbox,
        "apply",
        lambda *_: (tmp_path / "recipients.db").write_bytes(b"recipient map"),
    )
    called = []

    def start(args, **_kwargs):
        if args[1] == "is-active":
            assert (tmp_path / "target.json").is_file()
            return SimpleNamespace(stdout="active\n" * (len(args) - 2))
        assert (tmp_path / "recipients.db").is_file()
        assert not (tmp_path / "target.json").exists()
        called.append(args)

    monkeypatch.setattr(drv_module.subprocess, "run", start)
    instance = drv_module.MailInstance(
        uuid=uuid4(), name="mail-test", domain="example.test", mode="mailbox"
    )
    instance.dump_to_dp()
    assert called == [["systemctl", "reload-or-restart", "exordos-mail-rx.service"]]
    assert (tmp_path / "target.json").is_file()

    (tmp_path / "recipients.db").unlink()
    with pytest.raises(InvalidDataPlaneObjectError):
        instance.restore_from_dp()
