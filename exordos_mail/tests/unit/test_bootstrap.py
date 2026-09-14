# Copyright 2026 Genesis Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run the real DP bootstrap, with storage/systemctl isolated from the host.

Ordering is checked against the shipped unit contracts. Mount assertion tests
also use systemd's own evaluator when available; this is not a VM boot test.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT = "exordos-metapaas-mail-agent"
CONFIGURE = "exordos-metapaas-mail-configure"
BOOTSTRAP = "exordos-bootstrap.service"
BASE_AGENT_DROPIN = "exordos-universal-agent.service.d/20-mail-bootstrap.conf"


def unit_values(name: str, section: str, key: str) -> list[str]:
    """Keep repeated systemd directives (ConfigParser would lose assertions)."""
    values = []
    current_section = ""
    filename = name if name.endswith(".conf") else f"{name}.service"
    for line in (ROOT / "etc/systemd" / filename).read_text().splitlines():
        line = line.strip()
        if line.startswith("["):
            current_section = line.strip("[]")
        elif current_section == section and line.startswith(f"{key}="):
            value = line.split("=", 1)[1]
            if value:
                values.append(value)
            else:
                values.clear()
    return values


@pytest.mark.parametrize("name", [AGENT, CONFIGURE, BASE_AGENT_DROPIN])
def test_units_wait_for_bootstrap_without_requiring_success(name: str) -> None:
    for key in ("Wants", "After"):
        dependencies = " ".join(unit_values(name, "Unit", key)).split()
        assert BOOTSTRAP in dependencies
        if name != BASE_AGENT_DROPIN:
            assert "network-online.target" in dependencies
    # Requires/BindsTo would strand the recovery agent on bootstrap failure.
    for key in ("Requires", "Requisite", "BindsTo"):
        assert BOOTSTRAP not in " ".join(unit_values(name, "Unit", key)).split()


def test_agent_remains_enabled_without_bootstrap_success_gate() -> None:
    commands = [
        shlex.split(line.removeprefix("sudo "))
        for line in (ROOT / "exordos/images/dp_install.sh").read_text().splitlines()
        if line.startswith("sudo systemctl") and AGENT in line
    ]
    assert commands == [["systemctl", "enable", AGENT]]
    assert unit_values(AGENT, "Install", "WantedBy") == ["multi-user.target"]
    assert unit_values(AGENT, "Service", "Restart") == ["on-failure"]
    agent_unit = (ROOT / "etc/systemd" / f"{AGENT}.service").read_text()
    assert "Condition" not in agent_unit
    assert "Assert" not in agent_unit


def test_image_installs_ordering_for_the_base_config_delivery_agent() -> None:
    installer = (ROOT / "exordos/images/dp_install.sh").read_text()
    # Check the source, destination, and directory creation, not merely the
    # existence of a drop-in that might never make it into the DP image.
    assert (
        'sudo mkdir -p "${SYSTEMD_SERVICE_DIR}exordos-universal-agent.service.d"'
        in installer
    )
    assert (
        f'sudo cp "$GC_PATH/etc/systemd/{BASE_AGENT_DROPIN}" '
        f'"${{SYSTEMD_SERVICE_DIR}}{BASE_AGENT_DROPIN}"'
        in installer.replace("\\\n    ", "")
    )
    dropin = (ROOT / "etc/systemd" / BASE_AGENT_DROPIN).read_text()
    assert "Condition" not in dropin
    assert "Assert" not in dropin


def test_configure_asserts_both_mounts_and_only_conditions_on_mail_env() -> None:
    assert unit_values(CONFIGURE, "Unit", "RequiresMountsFor") == ["/persist /var/log"]
    assert unit_values(CONFIGURE, "Unit", "AssertPathIsMountPoint") == [
        "/persist",
        "/var/log",
    ]
    assert unit_values(CONFIGURE, "Unit", "ConditionPathExists") == [
        "/etc/exordos_metapaas/mail.env"
    ]
    assert not unit_values(CONFIGURE, "Service", "ConditionPathExists")
    assert not unit_values(CONFIGURE, "Unit", "ConditionPathIsMountPoint")


@pytest.mark.parametrize("name", [AGENT, BASE_AGENT_DROPIN])
def test_mount_failure_does_not_block_recovery_agents(name: str) -> None:
    assert not unit_values(name, "Unit", "RequiresMountsFor")


class BootstrapHarness:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.call_log = directory / "calls.log"
        self.library = directory / "lib_bootstrap.sh"
        self.library.write_text(
            """
record() {
    printf '%s\\n' "$*" >> "$CALL_LOG"
    if [[ "${FAIL_STAGE:-}" == "$1" ]]; then
        return 37
    fi
}
find_persistent_disk() {
    record find_persistent_disk || return $?
    printf '/dev/test-disk\\n'
}
prepare_persistent_disk() {
    record prepare_persistent_disk "$@"
    touch "$TEST_STATE/persist-mounted"
}
migrate_to_persistent_restart() {
    record migrate_to_persistent_restart "$@"
    touch "$TEST_STATE/log-mounted"
}
persist_migrate_complete() {
    record persist_migrate_complete
    # The real helper writes a marker and returns, without exiting/rebooting.
    touch "$TEST_STATE/bootstrap_success.txt"
}
"""
        )
        bin_path = directory / "bin"
        bin_path.mkdir()
        self._command(bin_path / "sudo", 'exec "$@"\n')
        self._command(
            bin_path / "systemctl",
            """
printf 'systemctl %s\\n' "$*" >> "$CALL_LOG"
if [[ "${FAIL_STAGE:-}" == systemctl ]]; then
    exit 37
fi
if [[ "$*" == "restart exordos-metapaas-mail-configure" ]]; then
    # Emulate mount availability, then let systemd evaluate the actual unit's
    # assertions. No host service is started, stopped or reloaded.
    set --
    for mount_path in $CONFIGURE_MOUNTS; do
        case "$mount_path" in
            /persist) marker=persist-mounted ;;
            /var/log) marker=log-mounted ;;
            *) exit 98 ;;
        esac
        path="$TEST_STATE"
        if [[ -f "$TEST_STATE/$marker" ]]; then path=/; fi
        set -- "$@" "AssertPathIsMountPoint=$path"
    done
    systemd-analyze condition "$@"
    touch "$TEST_STATE/configured"
    exit 0
fi
# A synchronous start would wait for the enclosing bootstrap job forever.
# Fail quickly rather than hang the test if --no-block regresses.
if [[ "$*" != "--no-block enable --now exordos-metapaas-mail-configure" ]]; then
    echo 'Unexpected or blocking systemctl invocation' >&2
    exit 99
fi
touch "$TEST_STATE/configure-queued"
""",
        )
        self.env = {
            **os.environ,
            "PATH": f"{bin_path}:{os.environ['PATH']}",
            "EXORDOS_BOOTSTRAP_LIB": str(self.library),
            "PERSISTENT_MOUNT": "/persist",
            "CALL_LOG": str(self.call_log),
            "TEST_STATE": str(directory),
            "FAIL_STAGE": "",
            "CONFIGURE_MOUNTS": " ".join(
                unit_values(CONFIGURE, "Unit", "AssertPathIsMountPoint")
            ),
        }

    @staticmethod
    def _command(path: Path, body: str) -> None:
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run(self, fail_stage: str = "") -> subprocess.CompletedProcess[str]:
        self.call_log.write_text("")
        return subprocess.run(
            ["bash", str(ROOT / "exordos/images/dp_bootstrap.sh")],
            env={**self.env, "FAIL_STAGE": fail_stage},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def calls(self) -> list[str]:
        return self.call_log.read_text().splitlines()

    def evaluate_mount_assertions(self) -> subprocess.CompletedProcess[str]:
        evaluator = shutil.which("systemd-analyze")
        if not evaluator:
            pytest.skip("systemd-analyze is needed for systemd assertion evaluation")
        # Storage operations are stubbed: map a mounted state to / (a real
        # mount point) and an unmounted state to this ordinary temp directory.
        markers = {"/persist": "persist-mounted", "/var/log": "log-mounted"}
        assertions = []
        for mount_path in unit_values(CONFIGURE, "Unit", "AssertPathIsMountPoint"):
            present = (self.directory / markers[mount_path]).exists()
            path = "/" if present else str(self.directory)
            assertions.append(f"AssertPathIsMountPoint={path}")
        assert assertions
        return subprocess.run(
            [evaluator, "condition", *assertions],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )


@pytest.fixture
def bootstrap(tmp_path: Path) -> BootstrapHarness:
    return BootstrapHarness(tmp_path)


EXPECTED_CALLS = [
    "find_persistent_disk",
    "prepare_persistent_disk /dev/test-disk /persist xfs",
    "migrate_to_persistent_restart /var/log /persist/var/log systemd-journald rsyslog",
    "persist_migrate_complete",
    f"systemctl --no-block enable --now {CONFIGURE}",
]


def test_bootstrap_queues_configuration_only_after_storage_is_ready(
    bootstrap: BootstrapHarness,
) -> None:
    result = bootstrap.run()
    assert result.returncode == 0, result.stderr
    assert bootstrap.calls() == EXPECTED_CALLS
    assert "Bootstrap completed successfully." in result.stdout
    for marker in (
        "persist-mounted",
        "log-mounted",
        "bootstrap_success.txt",
        "configure-queued",
    ):
        assert (bootstrap.directory / marker).exists()


@pytest.mark.parametrize("stage_index", range(len(EXPECTED_CALLS)))
def test_failure_is_not_masked_and_does_not_disable_agent(
    bootstrap: BootstrapHarness, stage_index: int
) -> None:
    result = bootstrap.run(EXPECTED_CALLS[stage_index].split()[0])
    assert result.returncode == 37, result.stderr
    assert bootstrap.calls() == EXPECTED_CALLS[: stage_index + 1]
    assert "Bootstrap completed successfully." not in result.stdout
    assert not (bootstrap.directory / "configure-queued").exists()
    assert all(AGENT not in call for call in bootstrap.calls())


def test_missing_library_fails_before_any_side_effect(
    bootstrap: BootstrapHarness,
) -> None:
    bootstrap.env["EXORDOS_BOOTSTRAP_LIB"] = str(bootstrap.directory / "missing.sh")
    result = bootstrap.run()
    assert result.returncode != 0
    assert bootstrap.calls() == []
    assert "Bootstrap completed successfully." not in result.stdout


@pytest.mark.parametrize(
    "stage",
    [
        "find_persistent_disk",
        "prepare_persistent_disk",
        "migrate_to_persistent_restart",
    ],
)
def test_storage_failure_blocks_configuration_until_repair(
    bootstrap: BootstrapHarness, stage: str
) -> None:
    result = bootstrap.run(stage)
    assert result.returncode == 37
    # Even if the base runner writes __done despite this child failure, mount
    # assertions fail visibly. Wants+After leaves the agent free to report it.
    (bootstrap.directory / "__done").touch()
    assert bootstrap.evaluate_mount_assertions().returncode != 0

    # Repair/retry is explicit; bootstrap does not have to enable/start the
    # agent on its success path, and no reset-failed operation is required.
    result = bootstrap.run()
    assert result.returncode == 0, result.stderr
    assert bootstrap.evaluate_mount_assertions().returncode == 0
    assert all(AGENT not in call for call in bootstrap.calls())


@pytest.mark.parametrize("missing", ["persist-mounted", "log-mounted"])
def test_either_lost_mount_rejects_configuration_even_with_success_marker(
    bootstrap: BootstrapHarness, missing: str
) -> None:
    assert bootstrap.run().returncode == 0
    (bootstrap.directory / missing).unlink()
    assert (bootstrap.directory / "bootstrap_success.txt").exists()
    assert bootstrap.evaluate_mount_assertions().returncode != 0
    (bootstrap.directory / missing).touch()
    assert bootstrap.evaluate_mount_assertions().returncode == 0


def test_mail_env_producer_hook_fails_and_recovers_in_base_render_consumer(
    bootstrap: BootstrapHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import grp
    import pwd
    import uuid
    from types import SimpleNamespace

    from gcl_sdk.agents.universal.drivers import render

    from exordos_mail.controlplane.infra.dm.models import MailInstance

    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze is needed for systemd assertion evaluation")

    # Use the real infra Config producer and the Render consumer installed in
    # the base agent, not the account-only MailCapabilityDriver.
    instance = SimpleNamespace(
        uuid=uuid.uuid4(), OnReloadFunc=MailInstance.OnReloadFunc
    )
    config = MailInstance._create_config(
        instance, uuid.uuid4(), uuid.uuid4(), "MAIL_DOMAIN=example.com\n"
    )
    assert config.path == "/etc/exordos_metapaas/mail.env"
    assert config.on_change.command == f"systemctl restart {CONFIGURE}"
    rendered = render.Render(
        uuid=config.uuid,
        path=str(bootstrap.directory / "mail.env"),
        content=config.body.content,
        mode=config.mode,
        owner=pwd.getpwuid(os.getuid()).pw_name,
        group=grp.getgrgid(os.getgid()).gr_name,
        on_change=render.OnChangeShell(command=config.on_change.command),
    )
    for key, value in bootstrap.env.items():
        monkeypatch.setenv(key, value)

    assert bootstrap.run("migrate_to_persistent_restart").returncode == 37
    with pytest.raises(subprocess.CalledProcessError):
        rendered.dump_to_dp()
    assert Path(rendered.path).read_text() == config.body.content
    assert not (bootstrap.directory / "configured").exists()

    # Retry the unchanged payload after storage repair. Render must propagate
    # the original failure and run the hook again, despite mail.env existing.
    assert bootstrap.run().returncode == 0
    rendered.dump_to_dp()
    assert (bootstrap.directory / "configured").exists()
    assert bootstrap.calls()[-1] == f"systemctl restart {CONFIGURE}"
