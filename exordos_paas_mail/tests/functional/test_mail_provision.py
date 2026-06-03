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

import pytest

import exordos_paas_mail.tests.functional.conftest as mail_conftest


class TestInstanceLifecycle:
    def test_instance_is_active(self, mail_instance):
        assert mail_instance["status"] == "ACTIVE"

    def test_instance_has_ips(self, mail_instance):
        ips = mail_instance.get("ipsv4", [])
        assert len(ips) >= 1

    def test_instance_domain_set(self, mail_instance):
        assert "." in mail_instance["domain"]


class TestAccountCRUD:
    def test_create_account(
        self, mail_api_client, mail_instance_uuid, mail_project_id
    ):
        username = f"user-{uuid.uuid4().hex[:8]}"
        # SHA512-CRYPT hash of "testpass"
        password_hash = "{SHA512-CRYPT}$6$rounds=5000$salt$hash"
        account = mail_conftest.create_account_via_api(
            mail_api_client,
            mail_instance_uuid,
            username,
            password_hash,
            mail_project_id,
        )
        assert account["username"] == username
        assert account.get("password_hash") is None  # hidden after create

        # Cleanup
        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.delete(collection, uuid=account["uuid"])

    def test_list_accounts(self, mail_api_client, mail_instance_uuid):
        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        accounts = mail_api_client.filter(collection)
        assert isinstance(accounts, list)

    def test_update_account_active(
        self, mail_api_client, mail_instance_uuid, mail_project_id
    ):
        username = f"update-{uuid.uuid4().hex[:8]}"
        password_hash = "$6$salt$hash"
        account = mail_conftest.create_account_via_api(
            mail_api_client,
            mail_instance_uuid,
            username,
            password_hash,
            mail_project_id,
        )

        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.update(collection, uuid=account["uuid"], active=False)

        updated = mail_api_client.get(collection, uuid=account["uuid"])
        assert updated["active"] is False

        # Cleanup
        mail_api_client.delete(collection, uuid=account["uuid"])

    def test_disable_account(
        self, mail_api_client, mail_instance_uuid, mail_project_id
    ):
        username = f"disabled-{uuid.uuid4().hex[:8]}"
        password_hash = "{SHA512-CRYPT}$6$rounds=5000$salt$hash"
        account = mail_conftest.create_account_via_api(
            mail_api_client,
            mail_instance_uuid,
            username,
            password_hash,
            mail_project_id,
        )

        collection = f"{mail_conftest.MAIL_INSTANCES}{mail_instance_uuid}/accounts/"
        mail_api_client.update(collection, uuid=account["uuid"], active=False)

        updated = mail_api_client.get(collection, uuid=account["uuid"])
        assert updated["active"] is False

        # Cleanup
        mail_api_client.delete(collection, uuid=account["uuid"])


class TestInstanceROFields:
    def test_domain_read_only_after_create(self, mail_api_client, mail_instance_uuid):
        with pytest.raises(Exception):
            mail_api_client.update(
                mail_conftest.MAIL_INSTANCES,
                uuid=mail_instance_uuid,
                domain="new-domain.example.com",
            )

    def test_disk_size_grow_ok(self, mail_api_client, mail_instance_uuid):
        instance = mail_api_client.get(
            mail_conftest.MAIL_INSTANCES, uuid=mail_instance_uuid
        )
        old_size = instance.get("disk_size", 0)
        mail_api_client.update(
            mail_conftest.MAIL_INSTANCES,
            uuid=mail_instance_uuid,
            disk_size=old_size + 10,
        )
        updated = mail_api_client.get(
            mail_conftest.MAIL_INSTANCES, uuid=mail_instance_uuid
        )
        assert updated["disk_size"] == old_size + 10

    def test_disk_size_shrink_fails(self, mail_api_client, mail_instance_uuid):
        instance = mail_api_client.get(
            mail_conftest.MAIL_INSTANCES, uuid=mail_instance_uuid
        )
        old_size = instance.get("disk_size", 0)
        with pytest.raises(Exception):
            mail_api_client.update(
                mail_conftest.MAIL_INSTANCES,
                uuid=mail_instance_uuid,
                disk_size=max(old_size - 1, 1),
            )
