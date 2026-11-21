# Developer guide

[Русский](guide.ru.md)

## Build and test

```bash
make build       # Build the wheel, the shared VM image and the element manifest
make test        # Run unit tests
make lint        # Check Python with Ruff
make format      # Format Python
make typecheck   # Check types with mypy
```

The element installs the exact wheel published as its build artifact.
To test a local build on a Realm, publish it to the element repository
used by that Realm and install the resulting version.

Run functional tests on an isolated Core and MetaPaaS Realm with
`mailaas` installed and reachable from the test runner. Set
`EXORDOS_PASSWORD` in the environment before running the command.

```bash
EXORDOS_ENDPOINT=http://10.20.0.2/api/core \
EXORDOS_USERNAME=admin \
EXORDOS_MAIL_CP_URL=http://10.20.0.2/api/metapaas \
make functional
```

The functional suite tests the SMTP-only API and authentication and
switches an instance through both modes. For MX changes, use a private
test domain and a local SMTP test sender and recipient.

## Source layout

| Path | Contents |
| ---- | -------- |
| `exordos_mail/controlplane/` | API, models, and infrastructure and service reconciliation |
| `exordos_mail/dataplane/` | Account and mailbox reconciliation on the VM |
| `exordos_mail/migrations/` | Control plane database migrations |
| `exordos_mail/tests/` | Unit and functional tests |
| `exordos/images/` | Image installation, bootstrap and configuration scripts |
| `exordos/manifests/` | Element manifest and example consumer element |
| `etc/systemd/`, `etc/mailbox/` | Service units and mailbox configuration templates |
| `examples/external-mx/` | Standalone inbound Postfix configuration and admin instructions |

## Data plane bootstrap

Bootstrap prepares the data disk and bind-mounts `/var/log`. It queues
the configure unit with `systemctl --no-block` because that unit is
ordered after bootstrap. The configure unit waits for `mail.env` from
the render agent and asserts that `/persist` and `/var/log` are mounted.
Both agents remain available for reporting and recovery when storage
initialization fails. After storage repair, the agent can retry the
configuration action.

Unit tests exercise the bootstrap script with command stubs. Use an
isolated Realm to verify first boot, actual systemd ordering and updates
that replace the root image.

## Documentation

Use Python 3.12 and tox with tox-uv.

```bash
uv tool install tox --with tox-uv
tox -e docs
tox -e docs-build
```

The local preview is at `http://127.0.0.1:8181`. The build writes to
`site/`. Edit both the English Markdown file and its `.ru.md` counterpart
when updating a page. The documentation workflow checks changes on pull
requests and can deploy the master build when GitHub Pages is configured
to use GitHub Actions.
