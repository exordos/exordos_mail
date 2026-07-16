#!/usr/bin/env python3
"""Prepare an Exordos Core environment for metapaas_mail integration testing.

Steps:
  1. Generate SSH key pair.
  2. Build metapaas_mail DP image + wheel (from --project-dir).
     Optionally build exordos_metapaas CP image (from --metapaas-dir).
  3. Serve mail artifacts via a local HTTP server; generate the root
     inventory.json the Core nginx repo driver requires.
  4. Register the local element repository in Core (exordos repo add),
     then install the metapaas element; wait for CP node ACTIVE.
  5. Install mailaas element; wait for PluginReconciler to activate mail plugin.
  6. Print env vars needed by the functional test suite.

Usage::

    python prepare_env.py \\
        --project-dir . \\
        --output-dir /tmp/metapaas-mail-build \\
        --endpoint http://10.20.0.2/api/core \\
        --username admin --password <pass>
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCAL_REPO_PATH = "/srv/exordos-local-repo/exordos-elements"
METAPAAS_PROJECT_ID = "4d657461-0000-0000-0000-000000000002"
METAPAAS_IAM_USER = "metapaas"
ZERO_PROJECT_ID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[prepare-env] {msg}", flush=True)


def _get_default_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    _log(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def _generate_ssh_key(key_dir: pathlib.Path) -> tuple[str, str]:
    key_dir.mkdir(parents=True, exist_ok=True)
    priv = key_dir / "id_rsa"
    pub = key_dir / "id_rsa.pub"
    if pub.exists():
        _log(f"SSH public key already exists: {pub}")
        return str(priv), str(pub)
    _run(
        [
            "ssh-keygen",
            "-t",
            "rsa",
            "-b",
            "4096",
            "-f",
            str(priv),
            "-N",
            "",
            "-C",
            "exordos-test",
        ]
    )
    _log(f"Generated SSH key pair in {key_dir}")
    return str(priv), str(pub)


def _build(
    project_dir: str, output_dir: str, pub_key: str, manifest_vars: dict
) -> None:
    cmd = [
        "exordos",
        "build",
        "-i",
        pub_key,
        "-f",
        "--output-dir",
        output_dir,
        project_dir,
    ]
    for k, v in manifest_vars.items():
        cmd += ["--manifest-var", f"{k}={v}"]
    _run(cmd)


def _build_wheel(project_dir: str, output_dir: str) -> pathlib.Path:
    """Build Python wheel for exordos_mail."""
    dist_dir = pathlib.Path(output_dir) / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        cwd=project_dir,
    )
    wheels = list(dist_dir.glob("exordos_mail-*.whl"))
    if not wheels:
        raise FileNotFoundError(f"No wheel found in {dist_dir}")
    _log(f"Built wheel: {wheels[0].name}")
    return wheels[0]


def _start_http_server(serve_dir: str, port: int) -> subprocess.Popen:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", port))
        except OSError:
            raise RuntimeError(f"Port {port} already in use")

    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", serve_dir],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    time.sleep(1)
    if proc.poll() is not None:
        raise RuntimeError(f"HTTP server failed to start on port {port}")
    _log(f"HTTP server: port={port} dir={serve_dir}")
    return proc


def _stop_http_server(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass


def _publish_to_serve_dir(
    serve_root: pathlib.Path,
    metapaas_output: pathlib.Path | None,
    mail_output: pathlib.Path,
    wheel_path: pathlib.Path,
) -> pathlib.Path:
    """Merge build outputs into the directory structure served over HTTP.

    ``exordos build`` writes ``<output>/exordos-elements/<name>/<version>/``
    (inventory.json, manifests/, images/, ...) — the exact layout the Core
    nginx repo driver expects, so the element trees are copied verbatim.

    elements:  serve_root/exordos-elements/<name>/<version>/...
    pip wheel: serve_root/simple/exordos_mail-*.whl
    """
    elements_root = serve_root / "exordos-elements"
    for output in (metapaas_output, mail_output):
        if output is None:
            continue
        src = output / "exordos-elements"
        if not src.is_dir():
            raise FileNotFoundError(f"No exordos-elements dir in build output {output}")
        shutil.copytree(src, elements_root, dirs_exist_ok=True)
        for inv in sorted(src.glob("*/*/inventory.json")):
            _log(f"  element: {inv.parent.relative_to(src)}")

    pip_dir = serve_root / "simple"
    pip_dir.mkdir(parents=True, exist_ok=True)
    dst = pip_dir / wheel_path.name
    if not dst.exists():
        shutil.copy2(wheel_path, dst)
    _log(f"  pip wheel: simple/{wheel_path.name}")
    return elements_root


def _generate_root_inventory(elements_root: pathlib.Path) -> None:
    """Write the root inventory.json the Core nginx repo driver requires.

    ``exordos build`` only writes per-element inventories; without
    ``<repo>/inventory.json`` the repository never becomes ACTIVE in Core.

    Format: ``{"elements": {<name>: {<version>: <element inventory>}}}``.
    """
    elements: dict[str, dict] = {}
    for inv_path in sorted(elements_root.glob("*/*/inventory.json")):
        version = inv_path.parent.name
        name = inv_path.parent.parent.name
        if version == "latest":
            continue
        elements.setdefault(name, {})[version] = json.loads(inv_path.read_text())
    root_inv = elements_root / "inventory.json"
    root_inv.write_text(json.dumps({"elements": elements}, indent=2, sort_keys=True))
    total = sum(len(v) for v in elements.values())
    _log(f"Root inventory: {root_inv} ({total} element version(s))")


def _ensure_core_repo(
    repo_url: str,
    endpoint: str,
    username: str,
    password: str,
) -> None:
    """Register repo_url as an element repository in Core (or refresh it)."""
    # Core's nginx driver joins element paths with urljoin, so the URL must
    # end with a slash or the last path segment gets replaced.
    repo_url = repo_url.rstrip("/") + "/"
    base_cmd = ["exordos", "-e", endpoint, "-u", username, "-p", password]
    result = subprocess.run(
        base_cmd + ["repo", "list", "-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    repos = json.loads(result.stdout)
    existing = next(
        (r for r in repos if r.get("uri", "").rstrip("/") == repo_url.rstrip("/")),
        None,
    )
    if existing is not None:
        _log(f"Repository {repo_url} already registered; refreshing")
        _run(base_cmd + ["repo", "refresh", existing["uuid"]])
        return
    # Derive the name from the URL so reruns with a different URL don't
    # collide with an existing repository name.
    netloc = urlparse(repo_url).netloc.replace(":", "-").replace(".", "-")
    _run(
        base_cmd
        + [
            "repo",
            "add",
            "-p",
            ZERO_PROJECT_ID,
            "-n",
            f"local-{netloc}",
            "--repo-url",
            repo_url,
            "--priority",
            "4096",
        ]
    )


def _ee_install(
    name: str,
    version: str,
    endpoint: str,
    username: str,
    password: str,
    timeout: int = 300,
) -> None:
    cmd = [
        "exordos",
        "-e",
        endpoint,
        "-u",
        username,
        "-p",
        password,
        "ee",
        "install",
        name,
    ]
    if version != "latest":
        cmd += ["--version", version]
    # A freshly registered repository is scanned asynchronously, so the
    # element may not be visible yet — retry until the scan completes.
    deadline = time.monotonic() + timeout
    while True:
        try:
            _run(cmd)
            return
        except subprocess.CalledProcessError:
            if time.monotonic() >= deadline:
                raise
            _log(f"Element '{name}' not installable yet; retrying in 10s…")
            time.sleep(10)


def _wait_for_element(
    name: str,
    target: str,
    endpoint: str,
    username: str,
    password: str,
    timeout: int = 300,
) -> None:
    _log(f"Waiting for element '{name}' to reach {target}…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["exordos", "-e", endpoint, "-u", username, "-p", password, "ee", "list"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if name in line:
                if target in line:
                    _log(f"Element '{name}' is {target}")
                    return
                if "ERROR" in line:
                    raise RuntimeError(f"Element '{name}' entered ERROR state")
        time.sleep(15)
    raise TimeoutError(f"Element '{name}' did not reach {target} within {timeout}s")


def _wait_for_node(
    name_pattern: str, endpoint: str, username: str, password: str, timeout: int = 300
) -> str:
    """Wait for a compute node matching name_pattern to be ACTIVE; return its IP."""
    _log(f"Waiting for node matching '{name_pattern}' to be ACTIVE…")
    deadline = time.monotonic() + timeout
    last_raw = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "exordos",
                "-e",
                endpoint,
                "-u",
                username,
                "-p",
                password,
                "cn",
                "list",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
        )
        last_raw = result.stdout
        try:
            nodes = json.loads(result.stdout)
        except Exception:
            time.sleep(15)
            continue
        for node in nodes if isinstance(nodes, list) else []:
            name = str(node.get("name", ""))
            status = str(node.get("status", ""))
            if name_pattern in name and status == "ACTIVE":
                for val in node.values():
                    m = re.search(r"\b(10\.\d+\.\d+\.\d+)\b", str(val))
                    if m:
                        ip = m.group(1)
                        _log(f"Node '{name}' ACTIVE at {ip}")
                        return ip
        time.sleep(15)
    _log(f"Last cn list output:\n{last_raw}")
    raise TimeoutError(f"No ACTIVE node matching '{name_pattern}' within {timeout}s")


def _get_metapaas_iam_password(cp_ip: str) -> str:
    """Read IAM_USER_PASS from /etc/exordos_init.txt on the metapaas CP."""
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=10",
                f"root@{cp_ip}",
                "grep IAM_USER_PASS /etc/exordos_init.txt | cut -d= -f2",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        pw = result.stdout.strip()
        if pw:
            return pw
    except Exception as e:
        _log(f"WARNING: Could not read IAM password via SSH: {e}")

    # Fallback: read via virsh guest-exec (if running on the hypervisor host)
    try:
        virsh_result = subprocess.run(
            ["sudo", "virsh", "list", "--all"],
            capture_output=True,
            text=True,
        )
        for line in virsh_result.stdout.splitlines():
            if "metapaas-cp" in line:
                vm_name = line.split()[1]
                script = "cat /etc/exordos_init.txt | grep IAM_USER_PASS | cut -d= -f2"
                enc = subprocess.run(
                    ["base64", "-w0"], input=script.encode(), capture_output=True
                ).stdout.decode()
                pid_result = subprocess.run(
                    [
                        "sudo",
                        "virsh",
                        "qemu-agent-command",
                        vm_name,
                        f'{{"execute":"guest-exec","arguments":{{"path":"/bin/bash","arg":["-c","echo {enc} | base64 -d | bash"],"capture-output":true}}}}',
                    ],
                    capture_output=True,
                    text=True,
                )
                pid = json.loads(pid_result.stdout)["return"]["pid"]
                time.sleep(2)
                status = subprocess.run(
                    [
                        "sudo",
                        "virsh",
                        "qemu-agent-command",
                        vm_name,
                        f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}',
                    ],
                    capture_output=True,
                    text=True,
                )
                import base64

                out = json.loads(status.stdout)["return"]
                pw = base64.b64decode(out.get("out-data", "")).decode().strip()
                if pw:
                    return pw
    except Exception as e:
        _log(f"WARNING: Could not read IAM password via virsh: {e}")

    return METAPAAS_IAM_USER  # fallback to default


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prepare Exordos Core for metapaas_mail integration testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--metapaas-dir",
        default=None,
        help="Path to exordos_metapaas source. If omitted, installs metapaas from the official repo.",
    )
    p.add_argument(
        "--project-dir",
        default=".",
        help="Path to metapaas_mail repository (default: .)",
    )
    p.add_argument("--output-dir", required=True, help="Directory for build output")
    p.add_argument("--key-dir", default=None, help="Directory for SSH key pair")
    p.add_argument(
        "-i", "--developer-key-path", default=None, help="Path to developer public key"
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip exordos build (use existing output)",
    )
    p.add_argument(
        "--http-port",
        type=int,
        default=8000,
        help="Port for the image HTTP server (default: 8000)",
    )
    p.add_argument(
        "--http-host",
        default=None,
        help="Host/IP for repository URL (default: auto-detect)",
    )
    p.add_argument(
        "--no-http-server",
        action="store_true",
        help="Do not start HTTP server (images served elsewhere)",
    )
    p.add_argument(
        "--metapaas-version",
        default="latest",
        help="metapaas element version to install",
    )
    p.add_argument(
        "--mail-version", default="0.0.1", help="mailaas element version to install"
    )
    p.add_argument(
        "--skip-install", action="store_true", help="Skip element installation"
    )
    p.add_argument(
        "--endpoint",
        default=os.environ.get("EXORDOS_ENDPOINT", "http://10.20.0.2/api/core"),
    )
    p.add_argument("--username", default=os.environ.get("EXORDOS_USERNAME", "admin"))
    p.add_argument("--password", default=os.environ.get("EXORDOS_PASSWORD", ""))
    p.add_argument(
        "--wait-timeout",
        type=int,
        default=600,
        help="Seconds to wait for elements/nodes to become ACTIVE",
    )
    p.add_argument(
        "--cleanup", action="store_true", help="Stop the HTTP server and exit"
    )
    p.add_argument(
        "--repository",
        default=None,
        help="Element repository base URL (overrides the auto-detected HTTP server URL).",
    )
    p.add_argument(
        "--elements-dir",
        default=None,
        help=(
            "Local filesystem path of the element repository served at "
            "--repository (e.g. the nginx root); a root inventory.json is "
            "(re)generated there before installing."
        ),
    )
    p.add_argument(
        "--index-url",
        dest="index_url",
        default=None,
        help="pip index URL (overrides the auto-detected HTTP server URL).",
    )
    p.add_argument("--pid-file", default=None)
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = pathlib.Path(args.output_dir)
    key_dir = (
        pathlib.Path(args.key_dir)
        if args.key_dir
        else pathlib.Path(tempfile.gettempdir()) / "exordos-test-keys"
    )
    pid_file = (
        pathlib.Path(args.pid_file)
        if args.pid_file
        else pathlib.Path(tempfile.gettempdir()) / "metapaas-http-server.pid"
    )

    if args.cleanup:
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                _log(f"Stopped HTTP server (PID {pid})")
            except ProcessLookupError:
                _log(f"HTTP server PID {pid} not running")
            pid_file.unlink(missing_ok=True)
        return

    # HTTP server base URL
    http_proc = None
    repository_url = None
    index_url = None

    if not args.no_http_server:
        host = args.http_host or _get_default_ip()
        port = args.http_port
        repository_url = f"http://{host}:{port}/exordos-elements"
        index_url = f"http://{host}:{port}/simple/"

    # Explicit CLI overrides always win (used when nginx is managed externally).
    if args.repository is not None:
        repository_url = args.repository
    if args.index_url is not None:
        index_url = args.index_url

    metapaas_output = output_dir / "metapaas"
    mail_output = output_dir / "mailaas"
    serve_root = output_dir / "serve"
    wheel_output = output_dir / "wheel"

    # ------------------------------------------------------------------
    # Step 1: SSH key
    # ------------------------------------------------------------------
    _log("Step 1: SSH key pair")
    _, pub_key = _generate_ssh_key(key_dir)
    pub_key = args.developer_key_path or pub_key

    # ------------------------------------------------------------------
    # Step 2: Build exordos_metapaas + exordos_mail
    # ------------------------------------------------------------------
    if not args.skip_build:
        if args.metapaas_dir is not None:
            _log("Step 2a: Building exordos_metapaas")
            mp_vars: dict[str, str] = {}
            if repository_url:
                mp_vars["repository"] = repository_url
            _build(args.metapaas_dir, str(metapaas_output), pub_key, mp_vars)
        else:
            _log(
                "Step 2a: Skipping exordos_metapaas build (will install from official repo)"
            )

        _log("Step 2b: Building metapaas_mail (DP image + manifests)")
        mail_vars: dict[str, str] = {}
        if repository_url:
            mail_vars["repository"] = repository_url
        if index_url:
            mail_vars["index_url"] = index_url
        _build(args.project_dir, str(mail_output), pub_key, mail_vars)

        _log("Step 2c: Building Python wheel for exordos_mail")
        wheel_path = _build_wheel(args.project_dir, str(wheel_output))
    else:
        _log("Step 2: Skipping build (--skip-build)")
        wheel_path = None

    # ------------------------------------------------------------------
    # Step 3: Publish to serve directory + start HTTP server
    # ------------------------------------------------------------------
    if not args.no_http_server:
        if wheel_path is None:
            # skip-build mode: locate a previously built wheel
            wheels = list((wheel_output / "dist").glob("exordos_mail-*.whl"))
            if not wheels:
                raise FileNotFoundError(
                    "No wheel found; run without --skip-build first"
                )
            wheel_path = wheels[0]

        _log("Step 3: Publishing artifacts")
        serve_root.mkdir(parents=True, exist_ok=True)
        elements_root = _publish_to_serve_dir(
            serve_root,
            metapaas_output if args.metapaas_dir is not None else None,
            mail_output,
            wheel_path,
        )
        _generate_root_inventory(elements_root)
        http_proc = _start_http_server(str(serve_root), port)
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(http_proc.pid))
        _log(f"Repository URL: {repository_url}")
        _log(f"Index URL:      {index_url}")
    else:
        _log("Step 3: Skipping local HTTP server (--no-http-server)")

    if args.elements_dir is not None:
        _generate_root_inventory(pathlib.Path(args.elements_dir))

    if args.skip_install:
        _log("Step 4-6: Skipping install (--skip-install)")
        _print_summary(repository_url, index_url, args, "?", "?")
        return

    # ------------------------------------------------------------------
    # Step 4: Register local repository + install metapaas element
    # ------------------------------------------------------------------
    if repository_url:
        _log("Step 4: Registering local element repository in Core")
        _ensure_core_repo(repository_url, args.endpoint, args.username, args.password)

    _log("Step 4: Installing metapaas element")
    _ee_install(
        "metapaas",
        args.metapaas_version,
        args.endpoint,
        args.username,
        args.password,
    )

    _log("Step 4a: Waiting for metapaas CP node ACTIVE")
    cp_ip = _wait_for_node(
        "metapaas-cp",
        args.endpoint,
        args.username,
        args.password,
        timeout=args.wait_timeout,
    )

    # ------------------------------------------------------------------
    # Step 5: Install mailaas element (triggers PluginReconciler)
    # ------------------------------------------------------------------
    _log("Step 5: Installing mailaas element")
    _ee_install(
        "mailaas",
        args.mail_version,
        args.endpoint,
        args.username,
        args.password,
    )

    _log(
        "Step 5a: Waiting for mailaas element ACTIVE (PluginReconciler installs plugin)"
    )
    _wait_for_element(
        "mailaas",
        "ACTIVE",
        args.endpoint,
        args.username,
        args.password,
        timeout=args.wait_timeout,
    )

    # ------------------------------------------------------------------
    # Step 6: Get metapaas IAM password
    # ------------------------------------------------------------------
    _log("Step 6: Reading metapaas IAM password")
    metapaas_password = _get_metapaas_iam_password(cp_ip)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    _print_summary(repository_url, index_url, args, cp_ip, metapaas_password)


def _print_summary(repository_url, index_url, args, cp_ip, metapaas_password) -> None:
    _log("=" * 60)
    _log("Environment ready! Suggested env vars for functional tests:")
    _log("")
    # Print without the [prepare-env] prefix so these lines are grep-able by CI.
    print(f"  export EXORDOS_ENDPOINT={args.endpoint}", flush=True)
    print(f"  export EXORDOS_USERNAME={args.username}", flush=True)
    print(f"  export EXORDOS_PASSWORD={args.password}", flush=True)
    print(f"  export METAPAAS_USERNAME={METAPAAS_IAM_USER}", flush=True)
    print(f"  export METAPAAS_PASSWORD={metapaas_password}", flush=True)
    print(f"  export EXORDOS_MAIL_CP_URL=http://{cp_ip}:8080", flush=True)
    print("  export EXORDOS_POLL_TIMEOUT=600", flush=True)
    _log("")
    _log("Then run:  tox -e py312-functional")
    _log("=" * 60)


if __name__ == "__main__":
    main()
