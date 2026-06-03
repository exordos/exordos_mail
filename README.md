# mail-aas: Mail Server PaaS Plugin for MetaPaaS

Mail server (Postfix SMTP + Dovecot IMAP/POP3) packaged as a MetaPaaS plugin,
following the same pattern as `metapaas_s3`.

## Architecture

```
metapaas-cp
└── mail plugin (exordos_paas_mail)
    ├── CP: MailInstance + MailAccount models, REST API, migrations
    ├── infra_builder: CoreInfraBuilder → NodeSet + Config on core
    └── paas_builder: MailInstanceBuilder → MailInstanceNode → DP agent

mail-aas-dp-<uuid> (VM)
└── Postfix (SMTP 25/587) + Dovecot (IMAP 143/993)
    ├── /etc/exordos_metapaas/mail.env    ← delivered by CP (MAIL_DOMAIN, MAIL_ROOT_PASSWORD)
    ├── /etc/exordos_metapaas/mail.users  ← managed by DP agent (Dovecot passwd-file)
    ├── /etc/postfix/vmailbox             ← managed by DP agent
    └── exordos-universal-agent           ← MailCapabilityDriver
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
exordos em elements install output/manifests/mail-aas.yaml
```

PluginReconciler on metapaas-cp installs `exordos_paas_mail` via pip and
activates the `/v1/types/mail/` route.

### Create Instance

```bash
# POST /v1/types/mail/instances
curl -X POST http://metapaas-cp:8080/v1/types/mail/instances \
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

### Create Mail Account

```bash
# POST /v1/types/mail/instances/<uuid>/accounts
HASH=$(openssl passwd -6 "mypassword")
curl -X POST http://metapaas-cp:8080/v1/types/mail/instances/<uuid>/accounts \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d "{
    \"username\": \"alice\",
    \"password_hash\": \"{SHA512-CRYPT}${HASH}\",
    \"project_id\": \"4d657461-0000-0000-0000-000000000002\",
    \"instance\": \"/v1/types/mail/instances/<uuid>\",
    \"quota_mb\": 1024
  }"
```

The agent on the DP node reconciles `/etc/exordos_metapaas/mail.users` (Dovecot
passwd-file) and `/etc/postfix/vmailbox` within seconds.

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
| PATCH  | `/v1/types/mail/instances/<uuid>/accounts/<uuid>` | Update (quota_mb, active, password_hash) |
| DELETE | `/v1/types/mail/instances/<uuid>/accounts/<uuid>` | Delete account |

### Field permissions

| Field | Create | Read | Update |
|-------|--------|------|--------|
| `domain` | RW | RO | RO |
| `status` | — | RO | RO |
| `ipsv4` | — | RO | RO |
| `root_password` | — | hidden | — |
| `password_hash` | RW | hidden | RW |
| `username` | RW | RO | RO |

## Repository Layout

```
.
├── exordos_paas_mail/
│   ├── constants.py          # MAIL_ENV_FILE, MAIL_USERS_FILE paths
│   ├── models.py             # MailVersion, MailInstance, MailAccount (restalchemy)
│   ├── permissions.py        # PERMS_OWNER list
│   ├── controllers.py        # REST controllers (gcl_iam policy-based)
│   ├── routes.py             # Route tree (instances/accounts, versions)
│   ├── definition.py         # MailDefinition (PaaSDefinition contract)
│   ├── infra_models.py       # MailInstance + infra (NodeSet + Config)
│   ├── infra_builder.py      # CoreInfraBuilder (creates VMs + delivers mail.env)
│   ├── paas_models.py        # MailInstanceNode (target resource for DP agent)
│   ├── paas_builder.py       # MailInstanceBuilder (maps accounts → DP payload)
│   ├── driver.py             # MailCapabilityDriver + MailInstance (Dovecot/Postfix reconcile)
│   ├── utils.py              # remove_nested_dm helper
│   ├── migrations/
│   │   └── 0000-init-mail.py # Creates mail_versions, mail_instances, mail_accounts tables
│   └── tests/
│       ├── unit/             # Unit tests (models, driver)
│       └── functional/       # E2E tests (prepare_env.py + test_mail_provision.py)
├── exordos/
│   ├── exordos.yaml          # Build config (deps + elements + DP image)
│   ├── images/
│   │   ├── dp_install.sh     # Packer: install Postfix/Dovecot/agent
│   │   └── dp_bootstrap.sh   # First-boot: persistent disk + start configure service
│   └── manifests/
│       ├── mail-aas.yaml.j2  # Element manifest: type reg + IAM + DP version
│       └── example_mail.yaml.j2  # Example consumer element
├── etc/
│   ├── systemd/
│   │   ├── exordos-metapaas-mail-configure.service  # Configures Postfix/Dovecot from mail.env
│   │   └── exordos-metapaas-mail-agent.service      # Universal agent (MailCapabilityDriver)
│   └── exordos_metapaas/
│       └── metapaas_mail_agent.conf  # Agent config (uuid5_name=mail-aas, endpoints)
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

export EXORDOS_MAIL_CP_URL=http://10.20.0.X:8080
tox -e py312-functional
```

## Key differences from metapaas_s3

| Aspect | s3aas | mail-aas |
|--------|-------|---------|
| DP software | RustFS | Postfix + Dovecot |
| Instance children | Bucket, Policy, User, AccessKey | Account |
| Replicas | 1–16 (single_node default) | Always 1 |
| Config delivered | `rustfs.env` (creds + ports) | `mail.env` (domain + root password) |
| On-change | `systemctl restart exordos-metapaas-rustfs` | `systemctl restart exordos-metapaas-mail-configure` |
| DP agent state file | `s3_meta.json` | `mail_meta.json` |
| uuid5 name | `s3aas` | `mail-aas` |

## References

- MetaPaaS design: `../exordos_metapaas/DESIGN.md`
- How to build new PaaS: `../metapaas_s3/HOW_TO_BUILD_NEW_PAAS.md`
- Working reference: `../metapaas_s3/`
