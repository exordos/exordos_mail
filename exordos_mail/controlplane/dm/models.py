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

import enum
import re

from gcl_sdk.agents.universal.dm import models as ua_models
from passlib.hash import sha512_crypt as _sha512_crypt
from restalchemy.common import exceptions as ra_exceptions
from restalchemy.dm import filters as dm_filters
from restalchemy.dm import models, properties, relationships, types
from restalchemy.storage.sql import orm

from exordos_mail import utils as u


def _is_crypt_hash(value: str) -> bool:
    """Return True if value is already a crypt hash or has a Dovecot-style prefix."""
    return value.startswith("$") or (value.startswith("{") and "}" in value)


class MailStatus(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"


class MailMode(str, enum.Enum):
    SMTP_ONLY = "smtp_only"
    MAILBOX = "mailbox"


MAIL_MODES = [mode.value for mode in MailMode]
MAILBOX_MIN_CPU = 2
MAILBOX_MIN_RAM = 1024  # MiB
DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
LOCAL_PART = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
CRYPT_HASH = re.compile(r"\$[A-Za-z0-9$./=,_-]+\Z")
RESERVED_NAMES = {"calendar-scheduler", "exordos-provisioner"}


class MailValidationError(ra_exceptions.ValidationErrorException):
    message = "%(reason)s"


class MailResourcesConflict(ra_exceptions.RestAlchemyException):
    code = 409
    message = "Mail mode, CPU, RAM or disk size changed concurrently. Reload and retry."


class MailVersion(
    models.ModelWithUUID,
    models.ModelWithNameDesc,
    models.ModelWithTimestamp,
    orm.SQLStorableMixin,
    ua_models.TargetResourceMixin,
):
    __tablename__ = "mail_versions"

    image = properties.property(types.String(max_length=2048))
    supports_mailbox = properties.property(types.Boolean(), default=False)

    def update(self, session=None, force=False):
        if not self.properties["image"].is_dirty():
            return super().update(session=session, force=force)
        with self._get_engine().session_manager(session=session) as txn:
            result = super().update(session=txn, force=force)
            txn.execute(
                "UPDATE mail_instances SET updated_at = now() WHERE version = %s",
                (str(self.uuid),),
            )
            return result


class MailInstance(
    models.ModelWithUUID,
    models.ModelWithNameDesc,
    models.ModelWithProject,
    models.ModelWithTimestamp,
    orm.SQLStorableMixin,
):
    __tablename__ = "mail_instances"

    name = properties.property(types.String(min_length=1, max_length=255))
    domain = properties.property(
        types.String(min_length=1, max_length=255), required=True
    )
    mode = properties.property(types.Enum(MAIL_MODES), default=MailMode.SMTP_ONLY.value)
    endpoints = properties.property(types.Dict(), default=dict)
    status = properties.property(
        types.Enum([status.value for status in MailStatus]),
        default=MailStatus.NEW.value,
    )
    ipsv4 = properties.property(
        types.TypedList(types.String(max_length=15)),
        default=list,
    )
    cpu = properties.property(types.Integer(min_value=1, max_value=128))
    ram = properties.property(types.Integer(min_value=512, max_value=1024**3))
    disk_size = properties.property(types.Integer(min_value=8, max_value=1024**3))
    version = relationships.relationship(MailVersion, required=True, read_only=True)
    # DKIM public key reported back from the data plane — publish it in DNS at
    # <dkim_selector>._domainkey.<domain>. Populated by the paas builder once
    # the configure script has generated the key on the node.
    dkim_public_key = properties.property(types.String(max_length=4096), default="")
    dkim_selector = properties.property(types.String(max_length=255), default="")

    def get_accounts(self, session=None):
        return MailAccount.objects.get_all(
            session=session, filters={"instance": dm_filters.EQ(self)}
        )

    def get_mailboxes(self, session=None):
        return Mailbox.objects.get_all(
            session=session, filters={"instance": dm_filters.EQ(self)}
        )

    def get_service_endpoints(self) -> dict:
        host = f"mail.{self.domain}"
        endpoints = {"submission": {"host": host, "port": 587, "tls": "starttls"}}
        if self.mode == MailMode.MAILBOX.value:
            endpoints.update(
                {
                    "imap": {"host": host, "port": 993, "tls": "implicit"},
                    "caldav": {"url": f"https://{host}:8443/dav/calendars/"},
                    "inbound_relay": {"host": host, "port": 2525, "tls": "starttls"},
                }
            )
        return endpoints

    def validate(self):
        super().validate()
        if (
            self.mode == MailMode.MAILBOX.value
            and self.version is not None
            and not self.version.supports_mailbox
        ):
            raise MailValidationError(
                reason="The image version must support mailbox mode"
            )

    def _validate_domain(self) -> None:
        if self.mode == MailMode.SMTP_ONLY.value and (
            not self.domain
            or not all(
                DOMAIN_LABEL.fullmatch(label)
                for label in self.domain.removesuffix(".").lower().split(".")
            )
        ):
            raise MailValidationError(reason="Use a DNS domain")
        if self.mode == MailMode.MAILBOX.value and (
            not self.domain
            or len(self.domain) > 248  # room for the mail. prefix in DNS
            or "." not in self.domain
            or not all(
                DOMAIN_LABEL.fullmatch(label) for label in self.domain.split(".")
            )
        ):
            raise MailValidationError(reason="Use a lowercase DNS domain")

    def _validate_resources(self):
        if self.mode == MailMode.MAILBOX.value and (
            self.cpu is None
            or self.cpu < MAILBOX_MIN_CPU
            or self.ram is None
            or self.ram < MAILBOX_MIN_RAM
        ):
            raise MailValidationError(
                reason=f"Mailbox requires at least {MAILBOX_MIN_CPU} vCPU and "
                f"{MAILBOX_MIN_RAM} MiB RAM"
            )

    def insert(self, session=None):
        self._validate_domain()
        self._validate_resources()
        return super().insert(session=session)

    def _validate_update(self, session=None):
        mode_changed = self.properties["mode"].is_dirty()
        if mode_changed or self.properties["domain"].is_dirty():
            self._validate_domain()
        if (
            mode_changed
            or self.properties["cpu"].is_dirty()
            or self.properties["ram"].is_dirty()
        ):
            self._validate_resources()
        disk_size = self.properties["disk_size"]
        if disk_size.is_dirty() and disk_size.old_value > self.disk_size:
            raise ValueError("disk_size shrink is not supported yet")

    def update(self, session=None, force=False):
        self._validate_update(session=session)
        if not (self.is_dirty() or force):
            return
        with self._get_engine().session_manager(session=session) as txn:
            current = MailInstance.objects.get_one(
                session=txn, locked=True, filters={"uuid": dm_filters.EQ(self.uuid)}
            )
            # Builders can stage VM targets before saving the instance. Reject a
            # stale size so the builder rolls back and reconciles the current size.
            for name in ("cpu", "ram", "disk_size", "mode"):
                prop = self.properties[name]
                if getattr(current, name) not in (prop.old_value, prop.value):
                    raise MailResourcesConflict()
            if self.mode != current.mode:
                if self.mode == MailMode.MAILBOX.value:
                    self._validate_mailbox_accounts(txn)
                self.status = MailStatus.IN_PROGRESS.value
                if self.ipsv4:
                    self.endpoints = self.get_service_endpoints()
            changes = {
                name: prop.value
                for name, prop in self.properties.items()
                if prop.is_dirty()
            }
            self.properties = current.properties
            self.update_dm(changes)
            return super().update(session=txn, force=force)

    def _validate_mailbox_accounts(self, session):
        for account in self.get_accounts(session=session):
            verifier = account.password_hash
            if verifier.startswith("{"):
                verifier = verifier.partition("}")[2]
            if (
                not LOCAL_PART.fullmatch(account.username)
                or account.username in RESERVED_NAMES
                or not CRYPT_HASH.fullmatch(verifier)
            ):
                raise MailValidationError(
                    reason="SMTP accounts must have mailbox-compatible names and passwords"
                )

    def delete(self, session=None, **kwargs):
        with self._get_engine().session_manager(session=session) as txn:
            current = MailInstance.objects.get_one(
                session=txn, locked=True, filters={"uuid": dm_filters.EQ(self.uuid)}
            )
            u.remove_nested_dm(Mailbox, "instance", current, session=txn)
            u.remove_nested_dm(MailAccount, "instance", current, session=txn)
            return super().delete(session=txn, **kwargs)


class MailAccount(
    models.ModelWithUUID,
    models.ModelWithNameDesc,
    models.ModelWithTimestamp,
    models.ModelWithProject,
    ua_models.TargetResourceMixin,
    orm.SQLStorableMixin,
):
    __tablename__ = "mail_accounts"

    instance = relationships.relationship(MailInstance, required=True, read_only=True)
    username = properties.property(
        types.String(min_length=1, max_length=255), required=True, read_only=True
    )
    # Plaintext password (write-only in the API). It is stored verbatim so the
    # EM target reconciles idempotently: the manifest always sends the same
    # plaintext, so target == actual. The salted crypt hash below can never
    # match a plaintext manifest value, which is what used to spin the builders.
    password = properties.property(
        types.String(min_length=1, max_length=1024), required=True
    )
    # exim4 crypt hash derived from `password` and pushed to the data plane.
    # Kept out of the EM resource (see get_resource_ignore_fields) because its
    # random salt would otherwise make the actual never match the target.
    password_hash = properties.property(types.String(max_length=1024), default="")
    active = properties.property(types.Boolean(), default=True)

    def get_resource_ignore_fields(self):
        # password_hash is a derived, per-save salted value; excluding it keeps
        # the account's EM resource stable so the db-back agent stops re-applying.
        return {"password_hash"}

    def _lock_parent(self, session) -> MailInstance:
        return MailInstance.objects.get_one(
            session=session,
            locked=True,
            filters={"uuid": dm_filters.EQ(self.instance.uuid)},
        )

    def _derive_hash(self, mode=None):
        # Recompute the crypt hash only when the plaintext changed (or is
        # missing), so an unchanged re-apply keeps the same salted hash and does
        # not needlessly reprovision the data plane. An already-hashed value
        # (e.g. backfilled from the old password_hash column) is used verbatim.
        if not self.properties["password"].is_dirty() and self.password_hash:
            return
        pw = self.password
        allow_verifier = (
            mode or (self.instance.mode if self.instance else None)
        ) != MailMode.MAILBOX.value
        self.password_hash = (
            pw if allow_verifier and _is_crypt_hash(pw) else _sha512_crypt.hash(pw)
        )

    def insert(self, session=None):
        with self._get_engine().session_manager(session=session) as txn:
            parent = self._lock_parent(txn)
            self._derive_hash(parent.mode)
            if parent.project_id != self.project_id:
                raise MailValidationError(
                    reason="An SMTP account requires a parent in the same project"
                )
            if parent.mode == MailMode.MAILBOX.value and (
                not LOCAL_PART.fullmatch(self.username)
                or self.username in RESERVED_NAMES
            ):
                raise MailValidationError(reason="Invalid SMTP account name")
            if any(
                self.username in (mailbox.local_part, *mailbox.aliases)
                for mailbox in parent.get_mailboxes(session=txn)
            ):
                raise MailValidationError(reason="A mailbox owns this address")
            super().insert(session=txn)
            parent.update(session=txn, force=True)

    def update(self, session=None, force=False):
        if not (self.is_dirty() or force) and self.password_hash:
            return
        changes = {
            name: self.properties[name].value
            for name in ("name", "description", "active", "password")
            if self.properties[name].is_dirty()
        }
        with self._get_engine().session_manager(session=session) as txn:
            parent = self._lock_parent(txn)
            current = MailAccount.objects.get_one(
                session=txn, filters={"uuid": dm_filters.EQ(self.uuid)}
            )
            self.properties = current.properties
            self.update_dm(changes)
            self._derive_hash(parent.mode)
            if self.is_dirty() or force:
                super().update(session=txn, force=force)
                parent.update(session=txn, force=True)

    def delete(self, session=None, **kwargs):
        with self._get_engine().session_manager(session=session) as txn:
            parent = self._lock_parent(txn)
            res = super().delete(session=txn, **kwargs)
            parent.update(session=txn, force=True)
            return res


class Mailbox(
    models.ModelWithUUID,
    models.ModelWithTimestamp,
    models.ModelWithProject,
    orm.SQLStorableMixin,
):
    __tablename__ = "mail_mailboxes"

    instance = relationships.relationship(MailInstance, required=True, read_only=True)
    local_part = properties.property(
        types.String(min_length=1, max_length=64), required=True, read_only=True
    )
    owner_user_uuid = properties.property(types.UUID(), required=True)
    aliases = properties.property(
        types.TypedList(types.String(max_length=64)), default=list
    )
    active = properties.property(types.Boolean(), default=True)
    address = properties.property(types.String(max_length=319), default="")
    status = properties.property(
        types.Enum([status.value for status in MailStatus]),
        default=MailStatus.NEW.value,
    )
    # The request password is cleared before storing or returning the model.
    password = properties.property(types.String(min_length=1, max_length=1024))
    password_hash = properties.property(types.String(max_length=1024), default="")

    def agent_spec(self) -> dict:
        return {
            "aliases": sorted(self.aliases),
            "active": self.active,
            "password_hash": self.password_hash,
        }

    def _prepare_save(self, session):
        instance = MailInstance.objects.get_one(
            session=session,
            locked=True,
            filters={"uuid": dm_filters.EQ(self.instance.uuid)},
        )
        if (
            instance.mode != MailMode.MAILBOX.value
            or instance.project_id != self.project_id
        ):
            raise MailValidationError(
                reason="A mailbox requires a mailbox-mode instance in the same project"
            )
        mailboxes = instance.get_mailboxes(session=session)
        previous = next(
            (mailbox for mailbox in mailboxes if mailbox.uuid == self.uuid), None
        )
        if previous is not None:
            # The ORM writes the whole row. Preserve fields omitted by this update.
            for name in ("owner_user_uuid", "active", "aliases"):
                if not self.properties[name].is_dirty():
                    setattr(self, name, getattr(previous, name))
        names = [self.local_part, *self.aliases]
        if len(set(names)) != len(names) or any(
            not LOCAL_PART.fullmatch(name) or name in RESERVED_NAMES for name in names
        ):
            raise MailValidationError(
                reason="Use unique lowercase local names (letters, digits, underscore, hyphen)"
            )
        addresses = set(names)
        for mailbox in mailboxes:
            if mailbox.uuid != self.uuid and addresses.intersection(
                (mailbox.local_part, *mailbox.aliases)
            ):
                raise MailValidationError(reason="An address already exists")
        if addresses.intersection(
            account.username for account in instance.get_accounts(session=session)
        ):
            raise MailValidationError(reason="An SMTP account owns this address")
        self.address = f"{self.local_part}@{instance.domain}"
        if self.password is not None:
            self.password_hash = _sha512_crypt.hash(self.password)
            self.password = None
        elif previous is not None:
            self.password_hash = previous.password_hash
        if not self.password_hash:
            raise MailValidationError(reason="A mailbox requires a password")
        return instance, previous

    def insert(self, session=None):
        with self._get_engine().session_manager(session=session) as txn:
            instance, _ = self._prepare_save(txn)
            super().insert(session=txn)
            instance.update(session=txn, force=True)

    def update(self, session=None, force=False):
        if not (self.is_dirty() or force):
            return
        with self._get_engine().session_manager(session=session) as txn:
            instance, previous = self._prepare_save(txn)
            self.status = (
                previous.status
                if previous is not None and previous.agent_spec() == self.agent_spec()
                else MailStatus.IN_PROGRESS.value
            )
            super().update(session=txn, force=True)
            instance.update(session=txn, force=True)

    @classmethod
    def record_applied(cls, instance, observed: dict) -> None:
        with instance._get_engine().session_manager() as session:
            parent = MailInstance.objects.get_one(
                session=session,
                locked=True,
                filters={"uuid": dm_filters.EQ(instance.uuid)},
            )
            for mailbox in parent.get_mailboxes(session=session):
                if (
                    mailbox.status != MailStatus.ACTIVE.value
                    and observed.get(mailbox.local_part) == mailbox.agent_spec()
                ):
                    mailbox.status = MailStatus.ACTIVE.value
                    orm.SQLStorableMixin.update(mailbox, session=session)
