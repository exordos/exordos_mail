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
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from gcl_sdk.infra.dm import models as sdk_models
from gcl_sdk.infra.services.builder import InfraCollection, InfraResourcePair
from passlib.hash import sha512_crypt

from exordos_mail.controlplane.dm import models
from exordos_mail.controlplane.infra.dm import models as infra_models
from exordos_mail.controlplane.infra.services.builder import CoreInfraBuilder
from exordos_mail.controlplane.paas.services.builder import MailInstanceBuilder


def _account(password, password_hash="", *, mode="smtp_only", cpu=1, ram=1024):
    version = models.MailVersion(
        uuid=uuid.uuid4(),
        name="exim4_1",
        image="http://repo/img",
        supports_mailbox=True,
    )
    instance = models.MailInstance(
        uuid=uuid.uuid4(),
        name="m",
        domain="ex.com",
        project_id=uuid.uuid4(),
        mode=mode,
        cpu=cpu,
        ram=ram,
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

    def test_smtp_only_domain_cannot_inject_exim_configuration(self) -> None:
        instance = _account("secret").instance
        instance.domain = "example.test'\ninvalid='value"
        with pytest.raises(models.MailValidationError, match="Use a DNS domain"):
            instance.insert()
        with pytest.raises(models.MailValidationError, match="Use a DNS domain"):
            instance._validate_update()

    def test_existing_smtp_only_domain_can_be_read_and_reconciled(self) -> None:
        instance = _account("secret").instance
        values = {name: prop.value for name, prop in instance.properties.items()}
        values["domain"] = "legacy.test.."
        restored = models.MailInstance.restore(**values)
        assert restored.domain == "legacy.test.."
        restored.status = models.MailStatus.ACTIVE.value
        restored._validate_update()

    @pytest.mark.parametrize("cpu, ram", [(1, 2048), (2, 512)])
    def test_mailbox_insert_rejects_undersized_vm(self, cpu, ram) -> None:
        instance = _account("secret", mode="mailbox", cpu=cpu, ram=ram).instance
        with pytest.raises(models.MailValidationError, match="2 vCPU and 1024 MiB"):
            instance.insert()

    def test_existing_undersized_mailbox_can_reconcile_and_upgrade(self) -> None:
        instance = _account("secret", mode="mailbox", ram=512).instance
        instance.status = models.MailStatus.ACTIVE.value
        instance._validate_update()

        instance.cpu = 2
        with pytest.raises(models.MailValidationError, match="2 vCPU and 1024 MiB"):
            instance._validate_update()
        instance.ram = 1024
        instance._validate_update()

    def test_enable_mailbox_with_existing_image_and_larger_resources(self) -> None:
        instance = _account("secret").instance
        instance.mode = "mailbox"
        instance.cpu = 2
        instance.ram = 2048
        instance._validate_update()

    def test_enable_mailbox_requires_mailbox_sizing(self) -> None:
        instance = _account("secret").instance
        instance.mode = "mailbox"
        with pytest.raises(models.MailValidationError, match="2 vCPU and 1024 MiB"):
            instance._validate_update()

    def test_disable_mailbox_allows_smtp_only_sizing(self) -> None:
        instance = _account("secret", mode="mailbox", cpu=2).instance
        instance.mode = "smtp_only"
        instance.cpu = 1
        instance.ram = 512
        instance._validate_update()

    def test_stale_endpoints_update_conflicts_after_disk_grow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance = _account("secret", mode="mailbox", cpu=2).instance
        current = _account("secret", mode="mailbox", cpu=2).instance
        current.disk_size = 30
        monkeypatch.setattr(
            models.MailInstance, "objects", SimpleNamespace(get_one=lambda **_: current)
        )
        monkeypatch.setattr(
            models.MailInstance,
            "_get_engine",
            lambda _: SimpleNamespace(session_manager=lambda **_: nullcontext()),
        )
        instance.endpoints = {"imap": {"port": 993}}

        with pytest.raises(models.MailResourcesConflict, match="disk size"):
            instance.update()


class TestMailbox:
    def test_alias_update_preserves_concurrent_disable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance = _account("secret", mode="mailbox", cpu=2).instance
        fields = {
            "uuid": uuid.uuid4(),
            "instance": instance,
            "project_id": instance.project_id,
            "local_part": "alice",
            "owner_user_uuid": uuid.uuid4(),
            "password_hash": "fixture",
        }
        current = models.Mailbox(active=False, **fields)
        stale = models.Mailbox(active=True, **fields)
        stale.aliases = ["support"]
        monkeypatch.setattr(
            models.MailInstance,
            "objects",
            SimpleNamespace(get_one=lambda **_: instance),
        )
        monkeypatch.setattr(
            models.MailInstance, "get_mailboxes", lambda *_args, **_kwargs: [current]
        )
        monkeypatch.setattr(
            models.MailInstance, "get_accounts", lambda *_args, **_kwargs: []
        )

        stale._prepare_save(session=None)

        assert stale.active is False
        assert stale.aliases == ["support"]


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

    def test_mailbox_mode_hashes_passwords_beginning_with_dollar(self) -> None:
        password = "$example+random"
        acc = _account(password)
        acc.instance.mode = models.MailMode.MAILBOX.value
        acc._derive_hash()
        assert sha512_crypt.verify(password, acc.password_hash)

    def test_password_hash_excluded_from_em_resource(self) -> None:
        acc = _account("s3cret")
        assert "password_hash" in acc.get_resource_ignore_fields()

    def test_mailbox_account_password_update_preserves_disabled_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = _account("old-password", mode="mailbox", cpu=2)
        values = {name: prop.value for name, prop in stale.properties.items()}
        current = models.MailAccount.restore(**(values | {"active": False}))
        monkeypatch.setattr(
            models.MailAccount, "objects", SimpleNamespace(get_one=lambda **_: current)
        )
        monkeypatch.setattr(
            models.MailAccount,
            "_get_engine",
            lambda _: SimpleNamespace(session_manager=lambda **_: nullcontext()),
        )
        monkeypatch.setattr(
            models.MailAccount, "_lock_parent", lambda self, session: stale.instance
        )
        monkeypatch.setattr(models.MailInstance, "update", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            models.orm.SQLStorableMixin, "update", lambda *args, **kwargs: None
        )
        stale.password = "new-password"

        stale.update()

        assert stale.active is False
        assert sha512_crypt.verify("new-password", stale.password_hash)


@pytest.mark.parametrize(
    ("initial_status", "cached_key"),
    [("IN_PROGRESS", ""), ("ACTIVE", ""), ("ACTIVE", "v=DKIM1; p=cached")],
)
def test_new_image_reports_active_with_dkim_identity(
    monkeypatch: pytest.MonkeyPatch,
    initial_status: str,
    cached_key: str,
) -> None:
    instance = _account("secret").instance
    instance.ipsv4 = ["198.51.100.25"]
    instance.status = initial_status
    instance.dkim_public_key = cached_key
    monkeypatch.setattr(
        models.MailInstance,
        "get_actual_nodeset",
        lambda self: SimpleNamespace(status="ACTIVE"),
        raising=False,
    )
    actual = SimpleNamespace(mode="smtp_only", status="ACTIVE", dkim_public_key="")
    collection = SimpleNamespace(actuals=lambda: (actual,))

    MailInstanceBuilder._sync_from_actuals(None, instance, collection)
    assert instance.status == "IN_PROGRESS"
    assert instance.dkim_public_key == cached_key

    actual.dkim_public_key = "v=DKIM1; k=rsa; p=fixture"
    actual.dkim_selector = "platform"
    MailInstanceBuilder._sync_from_actuals(None, instance, collection)
    assert instance.status == "ACTIVE"
    assert instance.dkim_public_key == actual.dkim_public_key
    assert instance.dkim_selector == actual.dkim_selector


def test_root_upgrade_waits_for_data_plane_preparation() -> None:
    instance = _account("secret").instance
    instance = infra_models.MailInstance.restore(
        **{name: prop.value for name, prop in instance.properties.items()}
    )
    project = uuid.uuid4()
    node = uuid.uuid4()
    target = next(iter(instance.get_infra(project)))
    actual = next(iter(instance.get_infra(project)))
    actual.nodes = {str(node): {"ipv4": "198.51.100.25"}}
    actual.status = "ACTIVE"
    old_image = "https://repo.example/old-image"
    for nodeset in (target, actual):
        nodeset.disk_spec = sdk_models.SetDisksSpec(
            disks=[
                {"size": 6, "image": old_image, "label": "root"},
                {"size": 10, "label": "data"},
            ]
        )
    builder = SimpleNamespace(
        _project_id=project, _cclient=SimpleNamespace(do_action=lambda *_: {})
    )
    nodeset_pair = InfraResourcePair(target, actual)

    waiting = CoreInfraBuilder.actualize_infra(
        builder, instance, InfraCollection((nodeset_pair,))
    )
    assert target.disk_spec.disks[0]["image"] == old_image
    configs = {
        item.path: item for item in waiting if isinstance(item, sdk_models.Config)
    }
    mail_env = configs.pop("/etc/exordos_metapaas/mail.env")
    assert "MAIL_MODE=smtp_only" in mail_env.body.content
    [check] = configs.values()
    assert "prepare-root" in check.on_change.command
    assert "import_keys /etc/exim4 /persist/mail" in check.body.content

    reported = instance.create_upgrade_check(node, project)
    reported.status = "ACTIVE"
    CoreInfraBuilder.actualize_infra(
        builder,
        instance,
        InfraCollection((nodeset_pair, InfraResourcePair(check, reported))),
    )
    assert target.disk_spec.disks[0]["image"] == instance.version.image
