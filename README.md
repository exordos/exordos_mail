# mail-aas: Mail Server PaaS Plugin for MetaPaaS

A complete mail server service (Postfix SMTP + Dovecot IMAP/POP3) packaged as a MetaPaaS plugin.

## Architecture

- **CP (Control Plane):** REST API for managing mail instances (Python package installed on metapaas-cp)
- **DP (Data Plane):** VM image running Postfix + Dovecot (Packer-built, deployed per instance)
- **Integration:** Automatic PluginReconciler installation on metapaas-cp

## Quick Start

### Build

```bash
make build \
  REPOSITORY=http://10.20.0.1:8080/exordos-elements \
  INDEX_URL=http://10.20.0.1:8080/simple/
```

Produces:
- `output/dist/exordos_paas_mail-1.0.0-py3-none-any.whl` (CP code)
- `output/exordos-metapaas-mail-dp.raw.zst` (DP image)
- `output/manifests/mail.yaml` (element manifest)

### Install

```bash
exordos -e http://10.20.0.2:11010 \
  -u admin -p <password> \
  ee install metapaas --version 1.0.0 --repository http://local-repo:8000/exordos-elements

exordos -e http://10.20.0.2:11010 \
  -u admin -p <password> \
  ee install mail --version 1.0.0 --repository http://local-repo:8000/exordos-elements
```

### Create Instance

```bash
curl -X POST http://metapaas-cp:8080/v1/types/mail/instances \
  -H 'Content-Type: application/json' \
  -u metapaas:<password> \
  -d '{
    "name": "mail-prod",
    "version": "1.0.0",
    "domain": "example.com",
    "max_users": 500,
    "backup_enabled": true,
    "spam_filter_enabled": true
  }'
```

## API Endpoints

### Instances

- `POST /v1/types/mail/instances` — Create
- `GET /v1/types/mail/instances` — List
- `GET /v1/types/mail/instances/{id}` — Get
- `PATCH /v1/types/mail/instances/{id}` — Update
- `DELETE /v1/types/mail/instances/{id}` — Delete

## Development

### Unit Tests

```bash
make test          # Run via tox
make lint          # Ruff check
make format        # Ruff format
make typecheck     # mypy
```

### Functional Tests

Requires live metapaas_core + metapaas + mail element:

```bash
make functional
```

Or with env vars:

```bash
EXORDOS_ENDPOINT=http://10.20.0.2:11010 \
EXORDOS_USERNAME=admin \
EXORDOS_PASSWORD=<pass> \
METAPAAS_USERNAME=metapaas \
METAPAAS_PASSWORD=<pass> \
EXORDOS_S3_CP_URL=http://10.20.0.X:8080 \
make functional
```

## Structure

```
.
├── exordos_paas_mail/          # Python CP package
│   ├── models.py               # SQLAlchemy MailInstance model
│   ├── controllers.py          # REST API endpoints
│   ├── iam_config.py           # IAM resource + roles
│   └── tests/                  # Unit + functional tests
├── exordos/
│   ├── exordos.yaml            # Build config (CP + DP + manifest)
│   ├── manifests/
│   │   └── mail.yaml.j2        # Element manifest template
│   └── mail-dp/
│       └── packer.pkr.hcl      # DP image Packer config
├── pyproject.toml              # Project metadata + dependencies
├── tox.ini                     # Test automation
├── Makefile                    # Build targets
└── .github/workflows/          # CI/CD
    ├── tests.yaml              # Unit tests
    └── func_tests.yaml         # E2E functional tests
```

## Configuration

### Manifest Variables

Control DP image and manifest rendering:

```bash
exordos build \
  --manifest-var repository=http://local.repo/exordos-elements \
  --manifest-var index_url=http://local.repo/simple/
```

### Instance Fields

- `name` (string) — Unique instance name
- `domain` (string) — Mail domain (e.g., example.com)
- `max_users` (integer) — Maximum mailbox users (default: 100)
- `backup_enabled` (boolean) — Enable automated backups (default: false)
- `spam_filter_enabled` (boolean) — Enable SpamAssassin (default: true)
- `virus_scan_enabled` (boolean) — Enable ClamAV (default: true)

## Troubleshooting

### Instance stuck in PENDING

Check PluginReconciler logs on metapaas-cp:

```bash
exordos -e http://10.20.0.2:11010 \
  -u admin -p <pass> \
  cn exec metapaas-cp -- \
  journalctl -u metapaas-plugin-reconciler -f
```

### Cannot connect to SMTP

Verify DP node is ACTIVE and ports 25/143/993 are listening:

```bash
# Get DP node IP
curl -s http://metapaas-cp:8080/v1/types/mail/instances/<id> \
  -u metapaas:<pass> | jq '.nodes[].ip'

# Test connectivity
telnet <ip> 25
```

### Permissions error

Ensure test user has `owner` role in METAPAAS_PROJECT_ID:

```bash
# Query IAM roles
curl -s http://10.20.0.2:11010/v1/iam/projects/4d657461-0000-0000-0000-000000000002/roles \
  -u admin:<pass>
```

## References

- MetaPaaS DESIGN: `../exordos_metapaas/DESIGN.md`
- How to build new PaaS: `../metapaas_s3/HOW_TO_BUILD_NEW_PAAS.md`
- Exordos docs: https://exordos.com/docs/
