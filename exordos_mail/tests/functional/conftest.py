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

from __future__ import annotations

import os
import time
import uuid as sys_uuid

import pytest
from exordos.clients import base_client
from gcl_iam.tests.functional import clients as iam_clients
from gcl_sdk.clients.http import base as http_client

EXORDOS_ENDPOINT = os.environ.get("EXORDOS_ENDPOINT", "http://10.20.0.2/api/core")
EXORDOS_USERNAME = os.environ.get("EXORDOS_USERNAME", "admin")
EXORDOS_PASSWORD = os.environ.get("EXORDOS_PASSWORD", "")

METAPAAS_PROJECT_ID = os.environ.get(
    "METAPAAS_PROJECT_ID", "4d657461-0000-0000-0000-000000000002"
)

METAPAAS_USERNAME = os.environ.get("METAPAAS_USERNAME", "metapaas")
METAPAAS_PASSWORD = os.environ.get("METAPAAS_PASSWORD", "")

EXORDOS_MAIL_CP_URL = os.environ.get("EXORDOS_MAIL_CP_URL", "")

POLL_TIMEOUT = int(os.environ.get("EXORDOS_POLL_TIMEOUT", "600"))
POLL_INTERVAL = int(os.environ.get("EXORDOS_POLL_INTERVAL", "15"))

MAIL_INSTANCES = "/v1/types/mail/instances/"
MAIL_VERSIONS = "/v1/types/mail/versions/"
NODE_COLLECTION = "/v1/compute/nodes/"

OWNER_ROLE_UUID = "726f6c65-0000-0000-0000-000000000002"
DEFAULT_CLIENT_UUID = "00000000-0000-0000-0000-000000000000"
DEFAULT_CLIENT_ID = "GenesisCoreClientId"
DEFAULT_CLIENT_SECRET = "GenesisCoreSecret"


def _get_auth_data(endpoint: str | None = None, project_id: str | None = None) -> dict:
    scope = None
    if project_id:
        scope = http_client.CoreIamAuthenticator.project_scope(
            sys_uuid.UUID(project_id)
        )
    return dict(
        endpoint=endpoint or EXORDOS_ENDPOINT,
        username=EXORDOS_USERNAME,
        password=EXORDOS_PASSWORD,
        access_token=None,
        refresh_token=None,
        scope=scope,
        client_uuid=DEFAULT_CLIENT_UUID,
        client_id=DEFAULT_CLIENT_ID,
        client_secret=DEFAULT_CLIENT_SECRET,
    )


@pytest.fixture(scope="session")
def core_client() -> http_client.CollectionBaseClient:
    return base_client.get_user_api_client(_get_auth_data())


@pytest.fixture(scope="session")
def iam_rest_client() -> iam_clients.GenericAutoRefreshRESTClient:
    auth = iam_clients.GenesisCoreAuth(
        username=EXORDOS_USERNAME,
        password=EXORDOS_PASSWORD,
        client_uuid=DEFAULT_CLIENT_UUID,
        client_id=DEFAULT_CLIENT_ID,
        client_secret=DEFAULT_CLIENT_SECRET,
    )
    endpoint = f"{EXORDOS_ENDPOINT.rstrip('/')}/v1/"
    return iam_clients.GenericAutoRefreshRESTClient(endpoint, auth)


@pytest.fixture(scope="session")
def mail_cp_ip(core_client) -> str:
    nodes = core_client.filter(NODE_COLLECTION, name="metapaas-cp")
    if not nodes:
        all_nodes = core_client.filter(NODE_COLLECTION)
        nodes = [n for n in all_nodes if "metapaas" in n.get("name", "").lower()]
    if not nodes:
        pytest.skip(
            "No metapaas-cp compute node found — is metapaas element installed?"
        )
    node = nodes[0]
    net = node.get("default_network", {})
    ip = net.get("ipv4")
    if not ip:
        pytest.skip("metapaas-cp node has no IP yet")
    return ip


@pytest.fixture(scope="session")
def metapaas_admin_client(mail_cp_ip) -> http_client.CollectionBaseClient:
    cp_url = EXORDOS_MAIL_CP_URL or f"http://{mail_cp_ip}:8080"
    metapaas_scope = http_client.CoreIamAuthenticator.project_scope(
        sys_uuid.UUID(METAPAAS_PROJECT_ID)
    )
    core_auth = http_client.CoreIamAuthenticator(
        base_url=EXORDOS_ENDPOINT,
        username=METAPAAS_USERNAME,
        password=METAPAAS_PASSWORD,
        scope=metapaas_scope,
    )
    return http_client.CollectionBaseClient(base_url=cp_url, auth=core_auth)


@pytest.fixture(scope="session")
def test_user(iam_rest_client) -> dict:
    test_password = f"Mailtest{sys_uuid.uuid4().hex[:12]}"
    user_name = f"mail-test-{sys_uuid.uuid4().hex[:8]}"
    user = iam_rest_client.create_user(
        username=user_name,
        password=test_password,
        first_name="Mail",
        last_name="Tester",
        email=f"noreply+{user_name}@genesis-core.tech",
    )
    user["password"] = test_password
    yield user
    try:
        iam_rest_client.delete_user(user["uuid"])
    except Exception:
        pass


@pytest.fixture(scope="session")
def test_user_project(iam_rest_client, test_user) -> dict:
    iam_rest_client.create_or_get_role_binding(
        role_uuid=OWNER_ROLE_UUID,
        user_uuid=test_user["uuid"],
        project_id=METAPAAS_PROJECT_ID,
    )
    yield {"uuid": METAPAAS_PROJECT_ID}


@pytest.fixture(scope="session")
def mail_api_client(
    mail_cp_ip, test_user, test_user_project
) -> http_client.CollectionBaseClient:
    mail_scope = http_client.CoreIamAuthenticator.project_scope(
        sys_uuid.UUID(test_user_project["uuid"])
    )
    core_auth = http_client.CoreIamAuthenticator(
        base_url=EXORDOS_ENDPOINT,
        username=test_user["username"],
        password=test_user["password"],
        scope=mail_scope,
    )
    cp_url = EXORDOS_MAIL_CP_URL or f"http://{mail_cp_ip}:8080"
    return http_client.CollectionBaseClient(base_url=cp_url, auth=core_auth)


@pytest.fixture(scope="session")
def mail_version_uuid(metapaas_admin_client) -> str:
    versions = metapaas_admin_client.filter(MAIL_VERSIONS)
    if not versions:
        pytest.skip("No mail versions registered — is mailaas element installed?")
    return versions[0]["uuid"]


@pytest.fixture(scope="session")
def mail_instance(mail_api_client, mail_version_uuid, test_user_project) -> dict:
    instance_name = f"test-mail-{sys_uuid.uuid4().hex[:8]}"
    data = {
        "name": instance_name,
        "project_id": test_user_project["uuid"],
        "domain": f"test-{sys_uuid.uuid4().hex[:6]}.example.com",
        "cpu": 1,
        "ram": 1024,
        "disk_size": 10,
        "version": f"{MAIL_VERSIONS}{mail_version_uuid}",
    }
    instance = mail_api_client.create(MAIL_INSTANCES, data=data)
    instance_uuid = instance["uuid"]
    yield _poll_instance_status(
        mail_api_client, instance_uuid, "ACTIVE", POLL_TIMEOUT, POLL_INTERVAL
    )
    try:
        mail_api_client.delete(MAIL_INSTANCES, uuid=instance_uuid)
    except Exception:
        pass


def _poll_instance_status(client, instance_uuid, target_status, timeout, interval):
    deadline = time.monotonic() + timeout
    last_status = ""
    while time.monotonic() < deadline:
        instance = client.get(MAIL_INSTANCES, uuid=instance_uuid)
        last_status = instance.get("status", "")
        if last_status == target_status:
            return instance
        if last_status in ("ERROR", "CREATE_FAILED", "DELETE_FAILED"):
            pytest.fail(f"Instance entered terminal status: {last_status}")
        time.sleep(interval)
    pytest.fail(
        f"Instance {instance_uuid} did not reach {target_status} "
        f"within {timeout}s (last: {last_status})"
    )


@pytest.fixture(scope="session")
def mail_instance_uuid(mail_instance) -> str:
    return mail_instance["uuid"]


@pytest.fixture(scope="session")
def mail_project_id(test_user_project) -> str:
    return test_user_project["uuid"]


def create_account_via_api(
    mail_api_client, instance_uuid, username, password_hash, project_id, **kwargs
):
    collection = f"{MAIL_INSTANCES}{instance_uuid}/accounts/"
    data = {
        "username": username,
        "password_hash": password_hash,
        "project_id": project_id,
        "instance": f"{MAIL_INSTANCES}{instance_uuid}",
        **kwargs,
    }
    result = mail_api_client.create(collection, data=data)
    time.sleep(5)
    return result
