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

import logging
import os
import time
import uuid as sys_uuid

import pytest
import requests
from bazooka import exceptions as bazooka_exc
from exordos.clients import base_client
from gcl_sdk.clients.http import base as http_client

LOG = logging.getLogger(__name__)

# --- Environment configuration ---

EXORDOS_ENDPOINT = os.environ.get("EXORDOS_ENDPOINT", "http://10.20.0.2/api/core")
EXORDOS_USERNAME = os.environ.get("EXORDOS_USERNAME", "admin")
EXORDOS_PASSWORD = os.environ.get("EXORDOS_PASSWORD", "")

# Metapaas project — mail versions and IAM permissions live here.
METAPAAS_PROJECT_ID = os.environ.get(
    "METAPAAS_PROJECT_ID", "4d657461-0000-0000-0000-000000000002"
)

# Mail CP URL — the metapaas user-api. Can be overridden; otherwise resolved
# from the metapaas-cp compute node.
EXORDOS_MAIL_CP_URL = os.environ.get("EXORDOS_MAIL_CP_URL", "")

POLL_TIMEOUT = int(os.environ.get("EXORDOS_POLL_TIMEOUT", "600"))
POLL_INTERVAL = int(os.environ.get("EXORDOS_POLL_INTERVAL", "15"))

# The core, the metapaas CP and the mail node share a single CI runner, so the
# core API blips under load: a request comes back 401 because IAM did not
# answer in time, and the token refresh that follows comes back 502.  None of
# that means the instance being polled is unhealthy.
TRANSIENT_API_ERRORS = (bazooka_exc.BaseHTTPException, requests.RequestException)
AUTH_ATTEMPTS = 5
AUTH_RETRY_INTERVAL = 5

MAIL_INSTANCES = "/v1/types/mail/instances/"
MAIL_VERSIONS = "/v1/types/mail/versions/"
NODE_COLLECTION = "/v1/compute/nodes/"

OWNER_ROLE_UUID = "726f6c65-0000-0000-0000-000000000002"

IAM_USERS = "/v1/iam/users/"
IAM_ROLE_BINDINGS = "/v1/iam/role_bindings/"


# --- Auth helpers ---


def _get_auth_data(endpoint: str | None = None, project_id: str | None = None) -> dict:
    scope = None
    if project_id:
        scope = http_client.CoreIamAuthenticator.project_scope(
            sys_uuid.UUID(project_id)
        )
    # Omit client_uuid so CoreIamAuthenticator uses its "default" alias and
    # sends no client_id/client_secret: `exordos bootstrap` generates a
    # per-stand secret for the default client, and sending a wrong one makes
    # core reject the password grant with invalid_client (401).
    return {
        "endpoint": endpoint or EXORDOS_ENDPOINT,
        "username": EXORDOS_USERNAME,
        "password": EXORDOS_PASSWORD,
        "access_token": None,
        "refresh_token": None,
        "scope": scope,
    }


class ResilientCoreIamAuthenticator(http_client.CoreIamAuthenticator):
    """A CoreIamAuthenticator that survives a blip in the core IAM API.

    Upstream falls back from the refresh-token grant to the password grant
    only on 400; anything else -- a 502 from an IAM busy reconciling a node --
    propagates out of ``authenticate()`` and poisons the client for the rest
    of the session.  Retry instead: the tests hold a username and a password,
    so a fresh password grant is always available.
    """

    def authenticate(self) -> None:
        for attempt in range(1, AUTH_ATTEMPTS + 1):
            try:
                super().authenticate()
                return
            except TRANSIENT_API_ERRORS as exc:
                if attempt == AUTH_ATTEMPTS:
                    raise
                LOG.warning(
                    "Authentication attempt %s/%s failed: %s",
                    attempt,
                    AUTH_ATTEMPTS,
                    exc,
                )
                # Whatever the cause, the refresh token is the part that can
                # be stale, so drop it and let the retry use the password.
                self._refresh_token = None
                time.sleep(AUTH_RETRY_INTERVAL)


# --- Core client fixture ---


@pytest.fixture(scope="session")
def core_client() -> http_client.CollectionBaseClient:
    return base_client.get_user_api_client(_get_auth_data())


# --- Metapaas CP node resolution ---


@pytest.fixture(scope="session")
def mail_cp_ip(core_client) -> str:
    """Find the host of the metapaas-cp API.

    Returns the host from EXORDOS_MAIL_CP_URL when it is set, so a stand that
    already knows where its CP lives does not pay for a core API call.
    """
    if EXORDOS_MAIL_CP_URL:
        return EXORDOS_MAIL_CP_URL.split("//", 1)[-1].split(":")[0]

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


# --- Test user and project ---


@pytest.fixture(scope="session")
def test_user(core_client) -> dict:
    test_password = f"Mailtest{sys_uuid.uuid4().hex[:12]}"
    user_name = f"mail-test-{sys_uuid.uuid4().hex[:8]}"
    user = core_client.create(
        IAM_USERS,
        data={
            "username": user_name,
            "password": test_password,
            "first_name": "Mail",
            "last_name": "Tester",
            "email": f"noreply+{user_name}@genesis-core.tech",
        },
    )
    user["password"] = test_password
    yield user
    try:
        core_client.delete(IAM_USERS, uuid=user["uuid"])
    except Exception:
        LOG.exception("Failed to clean up test user %s", user["uuid"])


@pytest.fixture(scope="session")
def test_user_project(core_client, test_user) -> dict:
    """Grant the test user the owner role in the metapaas project.

    The mail IAM permissions (mail_instance.*, account.*, mail_version.read)
    are bound to the owner role in the metapaas project.  Using a separate
    test project would mean re-creating all of those bindings; it is simpler
    to give the test user owner in the metapaas project for the session.
    """
    existing = core_client.filter(
        IAM_ROLE_BINDINGS,
        role=OWNER_ROLE_UUID,
        user=test_user["uuid"],
        project=METAPAAS_PROJECT_ID,
    )
    if not existing:
        core_client.create(
            IAM_ROLE_BINDINGS,
            data={
                "role": f"/v1/iam/roles/{OWNER_ROLE_UUID}",
                "user": f"/v1/iam/users/{test_user['uuid']}",
                "project": f"/v1/iam/projects/{METAPAAS_PROJECT_ID}",
            },
        )
    yield {"uuid": METAPAAS_PROJECT_ID}
    # Role binding cleanup is handled by user deletion in test_user teardown.


# --- Mail CP API client (test user scope) ---


@pytest.fixture(scope="session")
def mail_api_client(
    mail_cp_ip, test_user, test_user_project
) -> http_client.CollectionBaseClient:
    mail_scope = http_client.CoreIamAuthenticator.project_scope(
        sys_uuid.UUID(test_user_project["uuid"])
    )
    core_auth = ResilientCoreIamAuthenticator(
        base_url=EXORDOS_ENDPOINT,
        username=test_user["username"],
        password=test_user["password"],
        scope=mail_scope,
    )
    cp_url = EXORDOS_MAIL_CP_URL or f"http://{mail_cp_ip}:8080"
    return http_client.CollectionBaseClient(base_url=cp_url, auth=core_auth)


# --- Mail version (from the metapaas project) ---


@pytest.fixture(scope="session")
def mail_version_uuid(mail_api_client) -> str:
    """Get the first registered mail version.

    The versions live in the metapaas project, which is the project the test
    user is scoped to and owns — the same owner role that carries every other
    mail permission also carries mail_version.read, so no separate metapaas
    service account (and no reading of its generated password) is needed.
    """
    versions = mail_api_client.filter(MAIL_VERSIONS)
    if not versions:
        pytest.skip("No mail versions registered — is mailaas element installed?")
    return versions[0]["uuid"]


# --- Mail instance ---


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
    LOG.info(
        "Created mail instance %s (%s), waiting for ACTIVE",
        instance_name,
        instance_uuid,
    )
    yield _poll_instance_status(
        mail_api_client, instance_uuid, "ACTIVE", POLL_TIMEOUT, POLL_INTERVAL
    )
    try:
        mail_api_client.delete(MAIL_INSTANCES, uuid=instance_uuid)
    except Exception:
        LOG.exception("Failed to clean up mail instance %s", instance_uuid)


def _poll_instance_status(client, instance_uuid, target_status, timeout, interval):
    start = last_report = time.monotonic()
    deadline = start + timeout
    last_status = ""
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            instance = client.get(MAIL_INSTANCES, uuid=instance_uuid)
        except TRANSIENT_API_ERRORS as exc:
            # This fixture is session-scoped: one unlucky request would fail
            # every test in the run.  Keep polling until the deadline and
            # report the error only if the API never comes back.
            last_error = exc
            LOG.warning("Polling instance %s failed: %s", instance_uuid, exc)
            time.sleep(interval)
            continue
        last_error = None
        status = instance.get("status", "")
        elapsed = round(time.monotonic() - start)
        # A status change is news; otherwise say something every half minute
        # so a run that takes minutes does not look like a hung one.
        if status != last_status or time.monotonic() - last_report >= 30:
            LOG.info("Instance %s is %s after %ds", instance_uuid, status, elapsed)
            last_report = time.monotonic()
        last_status = status
        if last_status == target_status:
            LOG.info(
                "Instance %s reached %s after %ds",
                instance_uuid,
                target_status,
                elapsed,
            )
            return instance
        if last_status in ("ERROR", "CREATE_FAILED", "DELETE_FAILED"):
            pytest.fail(f"Instance entered terminal status: {last_status}")
        time.sleep(interval)
    detail = f"last status: {last_status or 'unknown'}"
    if last_error is not None:
        detail += f", last error: {last_error}"
    pytest.fail(
        f"Instance {instance_uuid} did not reach {target_status} "
        f"within {timeout}s ({detail})"
    )


# --- Derived fixtures ---


@pytest.fixture(scope="session")
def mail_instance_uuid(mail_instance) -> str:
    return mail_instance["uuid"]


@pytest.fixture(scope="session")
def mail_project_id(test_user_project) -> str:
    return test_user_project["uuid"]


def create_account_via_api(
    mail_api_client, instance_uuid, username, password, project_id, **kwargs
):
    """Create a mail account through the CP API.

    Returns as soon as the CP has accepted it.  The account reaches exim4 on
    the dataplane a moment later, so a test that authenticates against SMTP
    waits for that itself (``_wait_for_auth`` in test_smtp_auth.py) rather
    than everyone paying a flat sleep here.
    """
    collection = f"{MAIL_INSTANCES}{instance_uuid}/accounts/"
    data = {
        "username": username,
        # Write-only plaintext (or verbatim crypt hash); the CP derives the
        # exim4 hash. password_hash is no longer a writable API field.
        "password": password,
        "project_id": project_id,
        "instance": f"{MAIL_INSTANCES}{instance_uuid}",
        **kwargs,
    }
    return mail_api_client.create(collection, data=data)
