# SPDX-License-Identifier: Apache-2.0

"""Render mailbox credentials and recipient routing on the mailbox node."""

import grp
import imaplib
import os
import re
import ssl
import subprocess
import tempfile
import time
from pathlib import Path

STATE = Path("/persist/mail/control")
CALENDAR_USER = "calendar-scheduler"
TARGET_FORMAT = 2
PROVISION_USER = "exordos-provisioner"
LOCAL_PART = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
CRYPT_HASH = re.compile(r"\$[A-Za-z0-9$./=,_-]+\Z")


def write_atomic(
    path: Path, content: str, mode: int = 0o640, group: str | None = None
) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w") as stream:
        temp_path = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), mode)
            if group:
                os.fchown(stream.fileno(), 0, grp.getgrnam(group).gr_gid)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)


def _lookup(lines: dict[str, str]) -> str:
    return "".join(f"{key} {value}\n" for key, value in sorted(lines.items()))


def _password_hash(value: str) -> str:
    if value.startswith("{") and "}" in value:
        value = value.split("}", 1)[1]
    if not CRYPT_HASH.fullmatch(value):
        raise ValueError("Unsupported password verifier")
    return value


def _ensure_inboxes(mailboxes: dict) -> None:
    if not mailboxes:
        return
    password = (STATE / "provision.secret").read_text().strip()
    context = ssl.create_default_context(cafile=STATE.parent / "tls" / "trust.crt")
    for attempt in range(30):
        try:
            client = imaplib.IMAP4_SSL("localhost", 993, ssl_context=context, timeout=5)
            break
        except ConnectionRefusedError:
            if attempt == 29:
                raise
            time.sleep(0.3)
    with client:
        client.login(PROVISION_USER, password)
        for username in sorted(mailboxes):
            name = f"user/{username}"
            status, result = client.list('""', name)
            if status != "OK":
                raise RuntimeError(f"Cyrus could not list {name}: {result}")
            if not any(result):
                status, result = client.create(name)
                if status != "OK":
                    raise RuntimeError(f"Cyrus could not create {name}: {result}")


def apply(domain: str, accounts: dict, mailboxes: dict) -> None:
    credentials = {}
    allowed_senders = {}
    calendar_senders = []
    imap_credentials = {PROVISION_USER: (STATE / "provision.hash").read_text().strip()}
    recipients = {f"@{domain}": "unknown@discard.invalid"}
    calendar_hash = (STATE.parent / "tx" / "scheduler.hash").read_text().strip()
    credentials[CALENDAR_USER] = _password_hash(calendar_hash)

    for username, info in sorted(accounts.items()):
        if not LOCAL_PART.fullmatch(username) or username in (
            CALENDAR_USER,
            PROVISION_USER,
        ):
            raise ValueError("Invalid SMTP username")
        if info["active"]:
            sender = f"{username}@{domain}"
            credentials[sender] = _password_hash(info["password_hash"])
            allowed_senders[sender] = sender

    for username, info in sorted(mailboxes.items()):
        aliases = [username, *info["aliases"]]
        if any(
            not LOCAL_PART.fullmatch(alias) or alias in (CALENDAR_USER, PROVISION_USER)
            for alias in aliases
        ):
            raise ValueError("Invalid mailbox address")
        address = f"{username}@{domain}"
        for alias in aliases:
            recipient = f"{alias}@{domain}"
            if recipient in recipients or recipient in credentials:
                raise ValueError("Duplicate mailbox address")
            recipients[recipient] = address
        if info["active"]:
            digest = _password_hash(info["password_hash"])
            imap_credentials[username] = digest
            credentials[address] = digest
            addresses = [f"{alias}@{domain}" for alias in aliases]
            allowed_senders[address] = " : ".join(addresses)
            calendar_senders.extend(addresses)

    if calendar_senders:
        allowed_senders[CALENDAR_USER] = " : ".join(calendar_senders)

    # Publish the Postfix lookup last, after the authentication files. The map
    # consists of a single database, so aliases and the catch-all switch together.
    write_atomic(
        STATE / "imap.passwd",
        "".join(
            f"{name}:{password}\n"
            for name, password in sorted(imap_credentials.items())
        ),
        0o600,
    )
    _ensure_inboxes(mailboxes)
    write_atomic(
        STATE / "tx.passwd",
        "".join(
            f"{name}:{password}\n" for name, password in sorted(credentials.items())
        ),
        group="dovecot",
    )
    write_atomic(
        STATE / "senders",
        "".join(
            f"{name}:{senders}\n" for name, senders in sorted(allowed_senders.items())
        ),
        group="exordos-mail-sign",
    )
    with tempfile.TemporaryDirectory(dir=STATE) as directory:
        staged = Path(directory) / "recipients"
        staged.write_text(_lookup(recipients))
        staged.chmod(0o644)
        subprocess.run(["postmap", f"hash:{staged}"], check=True, timeout=10)
        os.replace(f"{staged}.db", STATE / "recipients.db")
