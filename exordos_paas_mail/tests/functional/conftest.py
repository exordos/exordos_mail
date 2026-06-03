"""Fixtures for functional tests."""

from __future__ import annotations

import os
import pytest
import requests
import socket
import time
from typing import Any, Generator


METAPAAS_PROJECT_ID = "4d657461-0000-0000-0000-000000000002"


@pytest.fixture(scope="session")
def mail_cp_ip() -> Generator[str, None, None]:
    """Resolve mail CP IP from env or node list."""
    cp_url = os.environ.get("EXORDOS_S3_CP_URL")
    if cp_url:
        # Extract IP from URL like "http://10.20.0.21:8080"
        ip = cp_url.split("://")[1].split(":")[0]
        yield ip
        return

    # Fallback: query core for metapaas-mail-cp node
    endpoint = os.environ.get("EXORDOS_ENDPOINT", "http://10.20.0.2:11010")
    username = os.environ.get("EXORDOS_USERNAME", "admin")
    password = os.environ.get("EXORDOS_PASSWORD", "")

    for _ in range(60):
        try:
            r = requests.get(
                f"{endpoint}/v1/compute/nodes",
                auth=(username, password),
                timeout=10,
            )
            if r.status_code == 200:
                for node in r.json().get("items", []):
                    if "mail-cp" in node.get("name", ""):
                        ip = node.get("ip")
                        if ip:
                            yield ip
                            return
        except Exception:
            pass

        time.sleep(10)

    pytest.skip("Could not resolve mail CP IP")


@pytest.fixture(scope="session")
def metapaas_admin_client() -> requests.Session:
    """Create authenticated client for metapaas user-api."""
    client = requests.Session()
    username = os.environ.get("METAPAAS_USERNAME", "metapaas")
    password = os.environ.get("METAPAAS_PASSWORD", "metapaas")
    client.auth = (username, password)
    return client


@pytest.fixture
def test_user_project(metapaas_admin_client: requests.Session) -> Generator[str, None, None]:
    """Create a test project and grant owner role to test user."""
    project_id = "test-mail-project"

    # Grant owner role in METAPAAS_PROJECT_ID (where permissions are bound)
    # Assuming the test user has a UUID from IAM
    # For now, this is a placeholder — real implementation would query user UUID first

    yield METAPAAS_PROJECT_ID


@pytest.fixture
def mail_api_client(metapaas_admin_client: requests.Session, mail_cp_ip: str) -> requests.Session:
    """Create authenticated client for mail service API."""
    client = requests.Session()
    client.base_url = f"http://{mail_cp_ip}:8080"
    client.auth = metapaas_admin_client.auth
    return client


@pytest.fixture
def mail_instance(
    mail_api_client: requests.Session,
    test_user_project: str,
) -> Generator[dict[str, Any], None, None]:
    """Create a test mail instance and clean up after."""
    payload = {
        "name": "test-mail-1",
        "version": "1.0.0",
        "domain": "test.example.com",
        "max_users": 10,
        "backup_enabled": False,
        "spam_filter_enabled": True,
    }

    r = mail_api_client.post(
        f"{mail_api_client.base_url}/v1/types/mail/instances",
        json=payload,
        timeout=30,
    )
    assert r.status_code == 201, f"Failed to create instance: {r.text}"
    instance = r.json()

    yield instance

    # Cleanup: delete instance
    instance_id = instance["id"]
    mail_api_client.delete(
        f"{mail_api_client.base_url}/v1/types/mail/instances/{instance_id}",
        timeout=30,
    )


@pytest.fixture
def wait_for_instance_active(
    mail_api_client: requests.Session,
    mail_cp_ip: str,
) -> Generator[callable, None, None]:
    """Fixture that returns a function to wait for instance ACTIVE status."""

    def _wait(instance_id: str, timeout: int = 300) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = mail_api_client.get(
                f"http://{mail_cp_ip}:8080/v1/types/mail/instances/{instance_id}",
                timeout=30,
            )
            if r.status_code == 200:
                instance = r.json()
                if instance.get("status") == "ACTIVE":
                    return instance
                if instance.get("status") in ["ERROR", "FAILED"]:
                    pytest.fail(f"Instance entered error state: {instance.get('status')}")
            time.sleep(10)

        pytest.fail(f"Instance {instance_id} did not reach ACTIVE within {timeout}s")

    yield _wait
