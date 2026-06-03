"""Functional tests for mail instance provisioning."""

from __future__ import annotations

import pytest
import requests
from typing import Any


@pytest.mark.functional
class TestMailInstanceProvisioning:
    """Test mail instance creation and lifecycle."""

    def test_create_mail_instance(
        self,
        mail_api_client: requests.Session,
        mail_cp_ip: str,
    ) -> None:
        """Test creating a mail instance."""
        payload = {
            "name": "test-mail-create",
            "version": "1.0.0",
            "domain": "create.test.com",
            "max_users": 20,
        }

        r = mail_api_client.post(
            f"http://{mail_cp_ip}:8080/v1/types/mail/instances",
            json=payload,
            timeout=30,
        )

        assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
        instance = r.json()
        assert instance["name"] == "test-mail-create"
        assert instance["domain"] == "create.test.com"
        assert instance["status"] in ["PENDING", "CREATING"]

        # Cleanup
        instance_id = instance["id"]
        mail_api_client.delete(
            f"http://{mail_cp_ip}:8080/v1/types/mail/instances/{instance_id}",
            timeout=30,
        )

    def test_list_mail_instances(
        self,
        mail_api_client: requests.Session,
        mail_cp_ip: str,
    ) -> None:
        """Test listing mail instances."""
        r = mail_api_client.get(
            f"http://{mail_cp_ip}:8080/v1/types/mail/instances",
            timeout=30,
        )

        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "items" in data or isinstance(data, list)

    def test_get_mail_instance(
        self,
        mail_api_client: requests.Session,
        mail_cp_ip: str,
        mail_instance: dict[str, Any],
    ) -> None:
        """Test retrieving a specific mail instance."""
        instance_id = mail_instance["id"]
        r = mail_api_client.get(
            f"http://{mail_cp_ip}:8080/v1/types/mail/instances/{instance_id}",
            timeout=30,
        )

        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        retrieved = r.json()
        assert retrieved["id"] == instance_id
        assert retrieved["domain"] == "test.example.com"

    def test_update_mail_instance(
        self,
        mail_api_client: requests.Session,
        mail_cp_ip: str,
        mail_instance: dict[str, Any],
    ) -> None:
        """Test updating mail instance configuration."""
        instance_id = mail_instance["id"]
        update_payload = {
            "max_users": 50,
            "backup_enabled": True,
        }

        r = mail_api_client.patch(
            f"http://{mail_cp_ip}:8080/v1/types/mail/instances/{instance_id}",
            json=update_payload,
            timeout=30,
        )

        # 200 or 204 are both acceptable
        assert r.status_code in [200, 204], f"Expected 200/204, got {r.status_code}: {r.text}"

        # Verify update
        r = mail_api_client.get(
            f"http://{mail_cp_ip}:8080/v1/types/mail/instances/{instance_id}",
            timeout=30,
        )
        assert r.status_code == 200
        updated = r.json()
        assert updated["max_users"] == 50
        assert updated["backup_enabled"] is True
