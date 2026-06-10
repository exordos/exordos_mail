#!/usr/bin/env python3
"""Prepare an Exordos Core environment for metapaas_mail integration testing.

Steps:
  1. Generate SSH key pair.
  2. Build metapaas_mail DP image + wheel (from --project-dir).
     Optionally build exordos_metapaas CP image (from --metapaas-dir).
  3. Serve mail artifacts via a local HTTP server.
  4. Install metapaas element (from official repo, or local if --metapaas-dir given);
     wait for CP node ACTIVE.
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
import shutil
import socket
import subprocess
import sys
import tempfile
import time

LOCAL_REPO_PATH = "/srv/exordos-local-repo/exordos-elements"
METAPAAS_PROJECT_ID = "4d657461-0000-0000-0000-000000000002"
METAPAAS_IAM_USER = "metapaas"


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


def _publish_to_serve_dir(
    serve_root: pathlib.Path,
    metapaas_output: pathlib.Path | None,
    mail_output: pathlib.Path,
    wheel_path: pathlib.Path,
) -> None:
    def _read_version(output_dir: pathlib.Path) -> str:
        inv = output_dir / "inventory.json"
        if inv.exists():
            data = json.loads(inv.read_text())
            if isinstance(data, list):
                data = data[0]
            return data.get("version", "0.0.1")
        return "0.0.1"

    if metapaas_output is not None:
        # metapaas CP image (only when built locally)
        mp_ver = _read_version(metapaas_output)
        mp_img_dir = serve_root / "metapaas" / mp_ver / "images"
        mp_img_dir.mkdir(parents=True, exist_ok=True)
        for img in (metapaas_output / "images").glob("*.zst"):
            dst = mp_img_dir / img.name
            if not dst.exists():
                shutil.copy2(img, dst)
            _log(f"  metapaas image: metapaas/{mp_ver}/images/{img.name}")

    # mailaas DP image + manifest
    mail_ver = _read_version(mail_output)
    mail_img_dir = serve_root / "mailaas" / mail_ver / "images"
    mail_img_dir.mkdir(parents=True, exist_ok=True)
    for img in (mail_output / "images").glob("*.zst"):
        dst = mail_img_dir / img.name
        if not dst.exists():
            shutil.copy2(img, dst)
        _log(f"  mailaas DP image: mailaas/{mail_ver}/images/{img.name}")
    for mf in (mail_output / "manifests").glob("*.yaml"):
        dst = serve_root / "mailaas" / mail_ver / mf.name
        shutil.copy2(mf, dst)
        _log(f"  mailaas manifest: mailaas/{mail_ver}/{mf.name}")

    # pip wheel
    pip_dir = serve_root / "simple"
    pip_dir.mkdir(parents=True, exist_ok=True)
    dst = pip_dir / wheel_path.name
    if not dst.exists():
        shutil.copy2(wheel_path, dst)
    _log(f"  pip wheel: simple/{wheel_path.name}")


def _ee_install(name, version, repository, endpoint, username, password):
    cmd = [
        "exordos", "-e", endpoint, "-u", username, "-p", password,
        "ee", "install", name,
        "--version", version,
    ]
    if repository is not None:
        cmd += ["--repository", repository]
    _run(cmd)


def _wait_for_element(name, target, endpoint, username, password, timeout=300):
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


def _wait_for_node(name_pattern, endpoint, username, password, timeout=300):
    _log(f"Waiting for node matching '{name_pattern}' to be ACTIVE…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["exordos", "-e", endpoint, "-u", username, "-p", password, "cn", "list"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if name_pattern in line and "ACTIVE" in line:
                import re

                m = re.search(r"\b(10\.\d+\.\d+\.\d+)\b", line)
                if m:
                    ip = m.group(1)
                    _log(f"Node '{name_pattern}' ACTIVE at {ip}")
                    return ip
        time.sleep(15)
    raise TimeoutError(f"No ACTIVE node matching '{name_pattern}' within {timeout}s")


def _get_metapaas_iam_password(cp_ip):
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
    return METAPAAS_IAM_USER


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prepare Exordos Core for metapaas_mail integration testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--metapaas-dir", default=None,
                   help="Path to exordos_metapaas source. If omitted, installs metapaas from the official repo.")
    p.add_argument("--project-dir", default=".")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--key-dir", default=None)
    p.add_argument("-i", "--developer-key-path", default=None)
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--http-port", type=int, default=8000)
    p.add_argument("--http-host", default=None)
    p.add_argument("--no-http-server", action="store_true")
    p.add_argument("--metapaas-version", default="latest")
    p.add_argument("--mail-version", default="0.0.1")
    p.add_argument("--skip-install", action="store_true")
    p.add_argument(
        "--endpoint",
        default=os.environ.get("EXORDOS_ENDPOINT", "http://10.20.0.2:11010"),
    )
    p.add_argument("--username", default=os.environ.get("EXORDOS_USERNAME", "admin"))
    p.add_argument("--password", default=os.environ.get("EXORDOS_PASSWORD", ""))
    p.add_argument("--wait-timeout", type=int, default=600)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    output_dir = pathlib.Path(args.output_dir)
    key_dir = (
        pathlib.Path(args.key_dir)
        if args.key_dir
        else pathlib.Path(tempfile.gettempdir()) / "exordos-test-keys"
    )

    repository_url = None
    index_url = None

    if not args.no_http_server:
        host = args.http_host or _get_default_ip()
        port = args.http_port
        repository_url = f"http://{host}:{port}/exordos-elements"
        index_url = f"http://{host}:{port}/simple/"

    metapaas_output = output_dir / "metapaas"
    mail_output = output_dir / "mailaas"
    serve_root = output_dir / "serve"
    wheel_output = output_dir / "wheel"

    _log("Step 1: SSH key pair")
    _, pub_key = _generate_ssh_key(key_dir)
    pub_key = args.developer_key_path or pub_key

    if not args.skip_build:
        if args.metapaas_dir is not None:
            _log("Step 2a: Building exordos_metapaas")
            mp_vars = {}
            if repository_url:
                mp_vars["repository"] = repository_url
            _build(args.metapaas_dir, str(metapaas_output), pub_key, mp_vars)
        else:
            _log("Step 2a: Skipping exordos_metapaas build (will install from official repo)")

        _log("Step 2b: Building metapaas_mail (DP image + manifests)")
        mail_vars = {}
        if repository_url:
            mail_vars["repository"] = repository_url
        if index_url:
            mail_vars["index_url"] = index_url
        _build(args.project_dir, str(mail_output), pub_key, mail_vars)

        _log("Step 2c: Building Python wheel for exordos_mail")
        wheel_path = _build_wheel(args.project_dir, str(wheel_output))
    else:
        _log("Step 2: Skipping build (--skip-build)")
        wheels = list((wheel_output / "dist").glob("exordos_mail-*.whl"))
        if not wheels:
            raise FileNotFoundError("No wheel found; run without --skip-build first")
        wheel_path = wheels[0]

    _log("Step 3: Publishing artifacts")
    serve_root.mkdir(parents=True, exist_ok=True)
    _publish_to_serve_dir(
        serve_root,
        metapaas_output if args.metapaas_dir is not None else None,
        mail_output,
        wheel_path,
    )

    if not args.no_http_server:
        _ = _start_http_server(str(serve_root), port)

    if args.skip_install:
        _log("Steps 4-6: Skipping install (--skip-install)")
        return

    _log("Step 4: Installing metapaas element")
    _ee_install(
        "metapaas",
        args.metapaas_version,
        repository_url if args.metapaas_dir is not None else None,
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

    _log("Step 5: Installing mailaas element")
    _ee_install(
        "mailaas",
        args.mail_version,
        repository_url,
        args.endpoint,
        args.username,
        args.password,
    )

    _log("Step 5a: Waiting for mailaas element ACTIVE")
    _wait_for_element(
        "mailaas",
        "ACTIVE",
        args.endpoint,
        args.username,
        args.password,
        timeout=args.wait_timeout,
    )

    _log("Step 6: Reading metapaas IAM password")
    metapaas_password = _get_metapaas_iam_password(cp_ip)

    _log("=" * 60)
    _log("Environment ready! Suggested env vars for functional tests:")
    _log("")
    _log(f"  export EXORDOS_ENDPOINT={args.endpoint}")
    _log(f"  export EXORDOS_USERNAME={args.username}")
    _log(f"  export EXORDOS_PASSWORD={args.password}")
    _log(f"  export METAPAAS_USERNAME={METAPAAS_IAM_USER}")
    _log(f"  export METAPAAS_PASSWORD={metapaas_password}")
    _log(f"  export EXORDOS_MAIL_CP_URL=http://{cp_ip}:8080")
    _log("  export EXORDOS_POLL_TIMEOUT=600")
    _log("")
    _log("Then run:  tox -e py312-functional")
    _log("=" * 60)


if __name__ == "__main__":
    main()
