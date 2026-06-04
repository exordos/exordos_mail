# mail-aas: SMTP Relay PaaS Plugin for MetaPaaS

exim4 SMTP submission server packaged as a MetaPaaS plugin,
following the same pattern as `metapaas_s3`.

## Architecture

```
metapaas-cp
└── mail plugin (exordos_paas_mail)
    ├── CP: MailInstance + MailAccount models, REST API, migrations
    ├── infra_builder: CoreInfraBuilder → NodeSet + Config on core
    └── paas_builder: MailInstanceBuilder → MailInstanceNode → DP agent

mail-aas-dp-<uuid> (VM)
└── exim4 (SMTP 25/465/587 — STARTTLS + auth)
    ├── /etc/exordos_metapaas/mail.env  ← delivered by CP (MAIL_DOMAIN)
    ├── /etc/exim4/passwd               ← managed by DP agent (lsearch auth)
    └── exordos-universal-agent         ← MailCapabilityDriver
```

## Quick Start

### Build

```bash
make build \
  REPOSITORY=http://10.20.0.1:8080/exordos-elements \
  INDEX_URL=http://10.20.0.1:8080/simple/
```

Produces:
- `output/images/exordos-metapaas-mail-dp.raw.zst` (DP image)
- `output/manifests/mail-aas.yaml` (element manifest)

### Install on running metapaas

```bash
make install
```

PluginReconciler on metapaas-cp installs `exordos_paas_mail` via pip and
activates the `/v1/types/mail/` route.

### Create Instance

```bash
curl -X POST http://metapaas-cp:8080/v1/types/mail/instances/ \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{
    "name": "mail-prod",
    "project_id": "4d657461-0000-0000-0000-000000000002",
    "domain": "example.com",
    "cpu": 2,
    "ram": 2048,
    "disk_size": 20,
    "version": "/v1/types/mail/versions/<version-uuid>"
  }'
```

### Create SMTP Account

```bash
# Generate SHA512-crypt hash (compatible with exim4 crypteq)
HASH=$(openssl passwd -6 "mypassword")

curl -X POST http://metapaas-cp:8080/v1/types/mail/instances/<uuid>/accounts/ \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d "{
    \"username\": \"alice\",
    \"password_hash\": \"${HASH}\",
    \"project_id\": \"4d657461-0000-0000-0000-000000000002\",
    \"instance\": \"/v1/types/mail/instances/<uuid>\"
  }"
```

Within seconds the DP agent writes the account to `/etc/exim4/passwd` and
reloads exim4. The user can then authenticate via SMTP AUTH (PLAIN/LOGIN over
STARTTLS on port 587 or SMTPS on port 465).

Hashes stored with a Dovecot `{SHA512-CRYPT}` scheme prefix are accepted — the
driver strips the prefix before writing to exim4's passwd file.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST   | `/v1/types/mail/instances/` | Create mail server |
| GET    | `/v1/types/mail/instances/` | List instances |
| GET    | `/v1/types/mail/instances/<uuid>` | Get instance |
| PATCH  | `/v1/types/mail/instances/<uuid>` | Update (cpu/ram/disk_size) |
| DELETE | `/v1/types/mail/instances/<uuid>` | Delete |
| GET    | `/v1/types/mail/versions/` | List DP image versions |
| POST   | `/v1/types/mail/instances/<uuid>/accounts/` | Create account |
| GET    | `/v1/types/mail/instances/<uuid>/accounts/` | List accounts |
| PATCH  | `/v1/types/mail/instances/<uuid>/accounts/<uuid>` | Update (active, password_hash) |
| DELETE | `/v1/types/mail/instances/<uuid>/accounts/<uuid>` | Delete account |

### Field permissions

| Field | Create | Read | Update |
|-------|--------|------|--------|
| `domain` | RW | RO | RO |
| `status` | — | RO | RO |
| `ipsv4` | — | RO | RO |
| `password_hash` | RW | hidden | RW |
| `username` | RW | RO | RO |
| `active` | RW | RW | RW |

## Repository Layout

```
.
├── exordos_paas_mail/
│   ├── constants.py          # MAIL_ENV_FILE, EXIM4_PASSWD_FILE paths
│   ├── models.py             # MailVersion, MailInstance, MailAccount (restalchemy)
│   ├── controllers.py        # REST controllers (gcl_iam policy-based)
│   ├── routes.py             # Route tree (instances/accounts, versions)
│   ├── definition.py         # MailDefinition (PaaSDefinition contract)
│   ├── infra_models.py       # MailInstance + infra (NodeSet + Config)
│   ├── infra_builder.py      # CoreInfraBuilder (creates VMs + delivers mail.env)
│   ├── paas_models.py        # MailInstanceNode (target resource for DP agent)
│   ├── paas_builder.py       # MailInstanceBuilder (maps accounts → DP payload)
│   ├── driver.py             # MailCapabilityDriver: writes /etc/exim4/passwd
│   ├── utils.py              # remove_nested_dm helper
│   ├── migrations/
│   │   ├── 0000-init-mail.py # Creates mail_versions, mail_instances, mail_accounts
│   │   └── 0001-drop-root-password.py
│   └── tests/
│       ├── unit/             # Unit tests (models, driver)
│       └── functional/       # E2E tests (prepare_env.py + SMTP auth tests)
├── exordos/
│   ├── exordos.yaml          # Build config (deps + elements + DP image)
│   ├── images/
│   │   ├── dp_install.sh     # Packer: install exim4 + configure script + agent
│   │   └── dp_bootstrap.sh   # First-boot: persistent disk + start configure service
│   └── manifests/
│       ├── mail-aas.yaml.j2  # Element manifest: type reg + IAM + DP version
│       └── example_mail.yaml.j2  # Example consumer element
├── etc/
│   ├── systemd/
│   │   ├── exordos-metapaas-mail-configure.service  # Configures exim4 from mail.env
│   │   └── exordos-metapaas-mail-agent.service      # Universal agent (MailCapabilityDriver)
│   └── exordos_metapaas/
│       ├── logging.yaml
│       └── metapaas_mail_agent.conf
├── .github/workflows/
│   ├── tests.yaml            # Lint (ruff) on every push
│   └── func_tests.yaml       # Full e2e: bootstrap core + deploy + SMTP tests
├── pyproject.toml
├── tox.ini
└── Makefile
```

## Development

```bash
make test          # Unit tests via tox
make lint          # ruff check
make format        # ruff format
make typecheck     # mypy
make functional    # E2E tests (needs live stand)
```

### Running functional tests manually

```bash
python exordos_paas_mail/tests/functional/prepare_env.py \
  --metapaas-dir ../exordos_metapaas \
  --project-dir . \
  --output-dir /tmp/mail-build \
  --endpoint http://10.20.0.2:11010 \
  --username admin --password <pass>

# Use env vars printed by prepare_env.py, then:
tox -e py312-functional
```

## Key differences from metapaas_s3

| Aspect | s3aas | mail-aas |
|--------|-------|---------|
| DP software | RustFS | exim4 (SMTP relay) |
| Instance children | Bucket, Policy, User, AccessKey | Account |
| Replicas | 1–16 | Always 1 |
| Config delivered | `rustfs.env` | `mail.env` (domain only) |
| DP auth state | S3 access keys | `/etc/exim4/passwd` (SHA512-crypt) |
| On-change | `systemctl restart rustfs` | `systemctl restart mail-configure` |
| DP agent state file | `s3_meta.json` | `mail_meta.json` |
| uuid5 name | `s3aas` | `mail-aas` |

## References

- MetaPaaS design: `../exordos_metapaas/DESIGN.md`
- How to build new PaaS: `../metapaas_s3/HOW_TO_BUILD_NEW_PAAS.md`
- Working reference: `../metapaas_s3/`
