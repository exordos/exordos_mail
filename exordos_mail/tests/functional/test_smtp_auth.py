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
"""Dataplane SMTP auth tests — verify CP→DP account sync against real exim4.

Each test authenticates against the actual SMTP server running on the mail DP
node.  No email is delivered outside the test domain: we use loopback
submission only.

Required env vars (see conftest.py):
  EXORDOS_ENDPOINT, EXORDOS_USERNAME, EXORDOS_PASSWORD,
  METAPAAS_USERNAME, METAPAAS_PASSWORD
Optional:
  EXORDOS_MAIL_CP_URL   — override metapaas-cp URL
  EXORDOS_POLL_TIMEOUT  — total seconds to wait for instance ACTIVE (default 600)
"""

from __future__ import annotations

import smtplib
import ssl
import time
import uuid

import pytest

import exordos_mail.tests.functional.conftest as mail_conftest


# --- Helpers ------------------------------------------------------------------

_TLS_CTX = ssl.create_default_context()
_TLS_CTX.check_hostname = False
_TLS_CTX.verify_mode = ssl.CERT_NONE  # self-signed cert on DP


def _smtp_login(host: str, username: str, password: str, port: int = 587, timeout: int = 10):
    """Open STARTTLS SMTP connection and attempt AUTH PLAIN.

    Returns the open smtp object on success so the caller can send mail.
    Raises smtplib.SMTPAuthenticationError on bad credentials.
    """
    smtp = smtplib.SMTP(host, port, timeout=timeout)
    smtp.ehlo()
    smtp.starttls(context=_TLS_CTX)
    smtp.ehlo()
    smtp.login(username, password)
    return smtp


def _wait_for_auth(
    host: str,
    username: str,
    password: str,
    expect_success: bool = True,
    timeout: int = 60,
    interval: int = 3,
    port: int = 587,
) -> None:
    """Poll until SMTP auth matches the expected outcome.

    Used to wait for CP→DP account propagation (or deletion).
    """
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            smtp = _smtp_login(host, username, password, port=port)
            smtp.quit()
            if expect_success:
                return
            # Auth succeeded but we expected failure — keep polling
        except smtplib.SMTPAuthenticationError as e:
            last_exc = e
            if not expect_success:
                return
        except (ConnectionRefusedError, OSError, smtplib.SMTPException):
            pass  # DP not ready yet
        time.sleep(interval)

    if expect_success:
        raise TimeoutError(
            f"SMTP auth for {username!r} did not succeed within {timeout}s"
            + (f": {last_exc}" if last_exc else "")
        )
    else:
        raise TimeoutError(
            f"SMTP auth for {username!r} did not fail within {timeout}s"
        )


def _sha512_crypt(password: str) -> str:
    """Return a raw SHA512-crypt hash suitable for exim4 lsearch ($6$...)."""
    import crypt  # noqa: PLC0415 — stdlib, Python ≤3.12

    return crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))


def _make_account(
    mail_api_client,
    instance_uuid: str,
    project_id: str,
    username: str,
    password: str,
    *,
    dovecot_prefix: bool = False,
) -> dict:
    """Create a mail account and return the API response.

    By default stores a raw SHA512-crypt hash ($6$...) that exim4 can verify
    directly.  Pass dovecot_prefix=True to store a Dovecot-formatted hash
    ({SHA512-CRYPT}$6$...) — the DP driver must strip the prefix before
    writing to /etc/exim4/passwd.
    """
    hashed = _sha512_crypt(password)
    password_hash = f"{{SHA512-CRYPT}}{hashed}" if dovecot_prefix else hashed
    return mail_conftest.create_account_via_api(
        mail_api_client,
        instance_uuid,
        username,
        password_hash,
        project_id,
    )


def _dp_ip(mail_instance: dict) -> str:
    ips = mail_instance.get("ipsv4", [])
    if not ips:
        pytest.skip("Mail instance has no IPs — DP not yet assigned")
    return ips[0]


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def dp_host(mail_instance) -> str:
    return _dp_ip(mail_instance)


@pytest.fixture(scope="module")
def domain(mail_instance) -> str:
    return mail_instance["domain"]


# --- Tests --------------------------------------------------------------------


class TestSmtpAuthBasic:
    """Basic SMTP AUTH mechanics against the real exim4 DP."""

    def test_auth_requires_tls(self, dp_host):
        """Without STARTTLS, exim4 must not advertise AUTH."""
        with smtplib.SMTP(dp_host, 587, timeout=10) as smtp:
            smtp.ehlo()
            # AUTH must not appear before STARTTLS
            caps = smtp.esmtp_features
            assert "auth" not in caps, (
                "AUTH advertised before STARTTLS — exim4 config wrong"
            )

    def test_valid_credentials_succeed(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Creating an account → SMTP AUTH with correct password succeeds."""
        username = f"valid-{uuid.uuid4().hex[:8]}"
        password = "CorrectHorseBatteryStaple1"
        _make_account(mail_api_client, mail_instance_uuid, mail_project_id, username, password)

        _wait_for_auth(dp_host, f"{username}@{domain}", password, expect_success=True)

        # Cleanup
        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        accounts = mail_api_client.filter(collection)
        for acc in accounts:
            if acc["username"] == username:
                mail_api_client.delete(collection, uuid=acc["uuid"])
                break

    def test_wrong_password_rejected(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """SMTP AUTH with wrong password must return 535."""
        username = f"badpw-{uuid.uuid4().hex[:8]}"
        password = "TheRealPassword99"
        _make_account(mail_api_client, mail_instance_uuid, mail_project_id, username, password)
        _wait_for_auth(dp_host, f"{username}@{domain}", password, expect_success=True)

        with pytest.raises(smtplib.SMTPAuthenticationError) as exc_info:
            _smtp_login(dp_host, f"{username}@{domain}", "WrongPassword99")
        assert exc_info.value.smtp_code == 535

        # Cleanup
        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        for acc in mail_api_client.filter(collection):
            if acc["username"] == username:
                mail_api_client.delete(collection, uuid=acc["uuid"])
                break

    def test_nonexistent_account_rejected(self, dp_host, domain):
        """AUTH for an account that was never created must return 535."""
        fake = f"ghost-{uuid.uuid4().hex[:8]}@{domain}"
        with pytest.raises(smtplib.SMTPAuthenticationError) as exc_info:
            _smtp_login(dp_host, fake, "anypassword")
        assert exc_info.value.smtp_code == 535

    def test_dovecot_prefix_stripped_by_driver(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Account stored with {SHA512-CRYPT} prefix must still authenticate.

        The DP driver is responsible for stripping the Dovecot scheme prefix
        before writing the hash to /etc/exim4/passwd.  This test verifies that
        the stripping logic is wired end-to-end.
        """
        username = f"prefix-{uuid.uuid4().hex[:8]}"
        password = "PrefixTest66"
        _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id,
            username, password, dovecot_prefix=True,
        )
        _wait_for_auth(dp_host, f"{username}@{domain}", password, expect_success=True)

        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        for acc in mail_api_client.filter(collection):
            if acc["username"] == username:
                mail_api_client.delete(collection, uuid=acc["uuid"])
                break


class TestSmtpAuthSync:
    """CP→DP account state propagation — the real integration surface."""

    def test_disabled_account_blocks_auth(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Setting active=False must revoke SMTP AUTH within sync window."""
        username = f"disable-{uuid.uuid4().hex[:8]}"
        password = "EnabledAtFirst77"
        acc = _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id, username, password
        )
        _wait_for_auth(dp_host, f"{username}@{domain}", password, expect_success=True)

        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.update(collection, uuid=acc["uuid"], active=False)

        _wait_for_auth(dp_host, f"{username}@{domain}", password, expect_success=False)

        mail_api_client.delete(collection, uuid=acc["uuid"])

    def test_deleted_account_blocks_auth(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Deleting an account must remove it from exim4 passwd within sync window."""
        username = f"delete-{uuid.uuid4().hex[:8]}"
        password = "SoonToBeGone88"
        acc = _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id, username, password
        )
        _wait_for_auth(dp_host, f"{username}@{domain}", password, expect_success=True)

        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.delete(collection, uuid=acc["uuid"])

        _wait_for_auth(dp_host, f"{username}@{domain}", password, expect_success=False)

    def test_password_update_takes_effect(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Updating password_hash must take effect on DP — old password stops working."""
        import crypt  # noqa: PLC0415

        username = f"repw-{uuid.uuid4().hex[:8]}"
        old_password = "OldPass111"
        new_password = "NewPass222"
        acc = _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id, username, old_password
        )
        _wait_for_auth(dp_host, f"{username}@{domain}", old_password, expect_success=True)

        new_hash = "{SHA512-CRYPT}" + crypt.crypt(
            new_password, crypt.mksalt(crypt.METHOD_SHA512)
        )
        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.update(collection, uuid=acc["uuid"], password_hash=new_hash)

        _wait_for_auth(dp_host, f"{username}@{domain}", new_password, expect_success=True)

        with pytest.raises(smtplib.SMTPAuthenticationError):
            _smtp_login(dp_host, f"{username}@{domain}", old_password)

        mail_api_client.delete(collection, uuid=acc["uuid"])

    def test_multiple_accounts_independent(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Multiple accounts must each authenticate with their own password only."""
        alice_pw = "AliceSecret42"
        bob_pw = "BobSecret43"
        alice = _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id,
            f"alice-{uuid.uuid4().hex[:6]}", alice_pw,
        )
        bob = _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id,
            f"bob-{uuid.uuid4().hex[:6]}", bob_pw,
        )
        alice_addr = f"{alice['username']}@{domain}"
        bob_addr = f"{bob['username']}@{domain}"

        _wait_for_auth(dp_host, alice_addr, alice_pw, expect_success=True)
        _wait_for_auth(dp_host, bob_addr, bob_pw, expect_success=True)

        with pytest.raises(smtplib.SMTPAuthenticationError):
            _smtp_login(dp_host, alice_addr, bob_pw)

        with pytest.raises(smtplib.SMTPAuthenticationError):
            _smtp_login(dp_host, bob_addr, alice_pw)

        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.delete(collection, uuid=alice["uuid"])
        mail_api_client.delete(collection, uuid=bob["uuid"])

    def test_reenabled_account_authenticates(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Disabling then re-enabling an account must restore SMTP AUTH."""
        username = f"reenable-{uuid.uuid4().hex[:8]}"
        password = "ToggleMe55"
        acc = _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id, username, password
        )
        addr = f"{username}@{domain}"
        _wait_for_auth(dp_host, addr, password, expect_success=True)

        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.update(collection, uuid=acc["uuid"], active=False)
        _wait_for_auth(dp_host, addr, password, expect_success=False)

        mail_api_client.update(collection, uuid=acc["uuid"], active=True)
        _wait_for_auth(dp_host, addr, password, expect_success=True)

        mail_api_client.delete(collection, uuid=acc["uuid"])


class TestSmtpSubmit:
    """SMTP submission session — no external delivery, loopback only."""

    def test_authenticated_user_can_submit_message(
        self, mail_api_client, mail_instance_uuid, mail_project_id, dp_host, domain
    ):
        """Authenticated user can submit a message (250 from DATA command).

        Delivery stays within the domain — exim4 may spool or bounce locally.
        No mail escapes the test environment.
        """
        username = f"submit-{uuid.uuid4().hex[:8]}"
        password = "SubmitPass99"
        _make_account(
            mail_api_client, mail_instance_uuid, mail_project_id, username, password
        )
        addr = f"{username}@{domain}"
        _wait_for_auth(dp_host, addr, password, expect_success=True)

        smtp = _smtp_login(dp_host, addr, password)
        try:
            result = smtp.sendmail(
                addr,
                [addr],
                f"From: {addr}\r\nTo: {addr}\r\nSubject: selftest\r\n\r\ntest",
            )
            # sendmail returns a dict of failed recipients; empty = all accepted
            assert result == {}, f"Unexpected send failures: {result}"
        finally:
            smtp.quit()

        # Cleanup
        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        for acc in mail_api_client.filter(collection):
            if acc["username"] == username:
                mail_api_client.delete(collection, uuid=acc["uuid"])
                break

    def test_unauthenticated_submission_fails(self, dp_host, domain):
        """Without AUTH, submission to the domain must not succeed.

        exim4 in Internet mode may accept MAIL FROM but reject RCPT TO for
        an unroutable domain (550), or reject at MAIL FROM (530).  Either way
        the mail is not accepted for delivery.
        """
        with smtplib.SMTP(dp_host, 587, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=_TLS_CTX)
            smtp.ehlo()
            try:
                smtp.sendmail(
                    f"noreply@{domain}",
                    [f"noreply@{domain}"],
                    "From: noreply\r\nTo: noreply\r\nSubject: test\r\n\r\ntest",
                )
                pytest.fail("sendmail should not succeed without authentication")
            except smtplib.SMTPSenderRefused as e:
                # Auth required before MAIL FROM
                assert e.smtp_code in (530, 550, 553)
            except smtplib.SMTPRecipientsRefused as e:
                # RCPT TO rejected (550 Unrouteable — domain not local)
                codes = {v[0] for v in e.recipients.values()}
                assert codes <= {550, 530, 553}
